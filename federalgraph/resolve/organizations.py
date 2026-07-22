from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from rapidfuzz import fuzz
from federalgraph.common import normalize_name, matching_tokens, acronym, domain, stable_id

@dataclass
class Candidate:
    left: int
    right: int
    score: float
    reasons: list[str]
    decision: str

class UnionFind:
    def __init__(self, n): self.p=list(range(n))
    def find(self,x):
        while self.p[x]!=x:
            self.p[x]=self.p[self.p[x]]; x=self.p[x]
        return x
    def union(self,a,b):
        a,b=self.find(a),self.find(b)
        if a!=b:self.p[b]=a

def _same_source(a,b): return a.get("source")==b.get("source")

def score_pair(a: dict, b: dict) -> tuple[float,list[str]]:
    na, nb = a.get("normalized_name", ""), b.get("normalized_name", "")
    ta, tb = set(matching_tokens(a.get("source_name", ""))), set(matching_tokens(b.get("source_name", "")))
    reasons=[]; score=0.0
    if na and na==nb:
        score=100; reasons.append("exact_normalized_name")
    else:
        ratio=fuzz.token_set_ratio(na,nb) if na and nb else 0
        score=max(score, ratio*0.75)
        if ratio>=90: reasons.append(f"high_name_similarity:{ratio:.0f}")
        if ta and tb:
            j=len(ta&tb)/len(ta|tb)
            score=max(score, j*85)
            if j>=0.75: reasons.append(f"high_token_overlap:{j:.2f}")
    aa,ab=a.get("acronym",""),b.get("acronym","")
    if aa and ab and aa==ab and len(aa)>=3:
        score=max(score,88); reasons.append("same_acronym")
    da,db=a.get("domain",""),b.get("domain","")
    if da and db and da==db:
        # Domain is corroborating evidence only, never identity by itself.
        score=min(100,score+8); reasons.append("same_domain_support")
    # Parent equality helps but cannot establish identity.
    pa,pb=a.get("normalized_parent_name",""),b.get("normalized_parent_name","")
    if pa and pb and pa==pb:
        score=min(100,score+5); reasons.append("same_parent_support")
    # Same-source records are usually separate named entities. Require exact name for merge.
    if _same_source(a,b) and na!=nb:
        score=min(score,89)
        reasons.append("same_source_separation_guard")
    return round(score,2),reasons

def _blocking_key(rec):
    tokens=matching_tokens(rec.get("source_name", ""))
    return (tokens[0] if tokens else "", rec.get("acronym", ""), rec.get("domain", ""))

def resolve(records: list[dict], auto_merge_threshold=96, review_threshold=72, hierarchy_threshold=80):
    n=len(records); uf=UnionFind(n)
    # Blocking avoids O(n^2) while retaining plausible candidates.
    blocks=defaultdict(set)
    for i,r in enumerate(records):
        tokens=matching_tokens(r.get("source_name", ""))
        for key in [r.get("normalized_name",""), r.get("acronym",""), r.get("domain","")] + tokens[:2]:
            if key and len(key)>=2: blocks[key].add(i)
    pairs=set()
    for ids in blocks.values():
        if len(ids)>80: continue
        for a,b in combinations(sorted(ids),2): pairs.add((a,b))
    candidates=[]
    for a,b in sorted(pairs):
        score,reasons=score_pair(records[a],records[b])
        if score < review_threshold: continue
        # Exact same source name in different sources can merge automatically; otherwise strict threshold.
        if score>=auto_merge_threshold and not (_same_source(records[a],records[b]) and records[a].get("normalized_name")!=records[b].get("normalized_name")):
            decision="auto_merge"; uf.union(a,b)
        else:
            decision="manual_review"
        candidates.append(Candidate(a,b,score,reasons,decision))
    groups=defaultdict(list)
    for i in range(n): groups[uf.find(i)].append(i)
    organizations=[]; source_rows=[]; idx_to_org={}
    for members in groups.values():
        member_recs=[records[i] for i in members]
        # Prefer USA.gov display name, then Federal Register, then longest name.
        ranked=sorted(member_recs,key=lambda r:(0 if r.get("source","").startswith("USA.gov") else 1 if r.get("source","").startswith("Federal Register") else 2,-len(r.get("source_name",""))))
        name=ranked[0].get("source_name","")
        oid=stable_id(name)
        aliases=sorted({r.get("source_name","") for r in member_recs if r.get("source_name")})
        domains=sorted({r.get("domain","") for r in member_recs if r.get("domain")})
        srcs=sorted({r.get("source","") for r in member_recs if r.get("source")})
        parents=sorted({r.get("parent_source_name","") for r in member_recs if r.get("parent_source_name")})
        org={
            "external_id":oid,"canonical_name":name,"normalized_name":normalize_name(name),
            "aliases":"|".join(aliases),"domains":"|".join(domains),"sources":"|".join(srcs),
            "parent_name_candidates":"|".join(parents),"source_record_count":len(member_recs),
            "resolution_status":"Auto-resolved" if len(member_recs)>1 else "Single-source provisional",
            "active_status":"Unreviewed"
        }
        organizations.append(org)
        for i,r in zip(members,member_recs):
            idx_to_org[i]=oid
            sr=dict(r); sr["canonical_external_id"]=oid
            sr["match_method"]="auto_merge" if len(member_recs)>1 else "new_entity"
            source_rows.append(sr)
    # Match candidate output and review queue
    candidate_rows=[]; review=[]
    for c in candidates:
        a,b=records[c.left],records[c.right]
        row={
            "left_source":a.get("source"),"left_source_record_id":a.get("source_record_id"),"left_name":a.get("source_name"),
            "right_source":b.get("source"),"right_source_record_id":b.get("source_record_id"),"right_name":b.get("source_name"),
            "score":c.score,"reasons":"|".join(c.reasons),"decision":c.decision,
            "left_canonical_external_id":idx_to_org[c.left],"right_canonical_external_id":idx_to_org[c.right]
        }
        candidate_rows.append(row)
        if c.decision=="manual_review":
            review.append({**row,"review_action":"merge / keep separate / hierarchy / historical alias","review_notes":""})
    # Hierarchy candidates are separate from identity.
    name_to_ids=defaultdict(list)
    for i,r in enumerate(records): name_to_ids[r.get("normalized_name","")].append(i)
    relationships=[]
    seen_rel=set()
    for i,r in enumerate(records):
        parent_norm=r.get("normalized_parent_name","")
        if not parent_norm: continue
        possible=name_to_ids.get(parent_norm,[])
        for p in possible:
            parent_id,child_id=idx_to_org[p],idx_to_org[i]
            if parent_id==child_id: continue
            key=(parent_id,child_id)
            if key in seen_rel: continue
            seen_rel.add(key)
            relationships.append({
                "parent_org_id":parent_id,"child_org_id":child_id,"relationship_type":"parent/component",
                "source":r.get("source"),"confidence":"High" if r.get("parent_source_name") else "Medium",
                "review_status":"Provisional","evidence":r.get("parent_source_name","")
            })
    # Status evidence. Presence is evidence; status remains unreviewed.
    status=[]
    for org in organizations:
        srcset=set(org["sources"].split("|")) if org["sources"] else set()
        status.append({
            "external_id":org["external_id"],"canonical_name":org["canonical_name"],
            "found_in_usagov":any(s.startswith("USA.gov") for s in srcset),
            "found_in_federal_register":any(s.startswith("Federal Register") for s in srcset),
            "found_in_program_inventory":any(s.startswith("Current Federal") for s in srcset),
            "suggested_status":"Likely current" if any(s.startswith("USA.gov") for s in srcset) else "Needs status review",
            "status_basis":"USA.gov presence" if any(s.startswith("USA.gov") for s in srcset) else "No current-directory confirmation",
            "review_status":"Unreviewed"
        })
    organizations=sorted(organizations,key=lambda r:r["canonical_name"].lower())
    return organizations,source_rows,candidate_rows,relationships,review,status
