from __future__ import annotations
from pathlib import Path
import pandas as pd
from federalgraph.common import ensure_dir

def export(organizations_csv: Path, out_path: Path):
    df=pd.read_csv(organizations_csv).fillna("")
    df.insert(0,"post_title",df["canonical_name"])
    df.insert(1,"post_slug",df["normalized_name"].str.replace(" ","-",regex=False))
    ensure_dir(out_path.parent)
    df.to_csv(out_path,index=False)
