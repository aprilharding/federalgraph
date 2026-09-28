from pathlib import Path

from federalgraph.extract.uscode_authority import extract_purpose_candidate, section_records_from_xml


def test_uscode_xml_section_lookup_and_purpose_signal(tmp_path: Path):
    xml = tmp_path / "usc07.xml"
    xml.write_text(
        '''<?xml version="1.0" encoding="UTF-8"?>
        <usc xmlns="http://xml.house.gov/schemas/uslm/1.0">
          <section><num>§ 1234</num><heading>Example program</heading>
          <subsection><content>The Secretary shall establish an Example Program to improve rural access.</content></subsection>
          </section>
        </usc>''',
        encoding="utf-8",
    )
    found = section_records_from_xml(xml, {"1234"})
    assert found["1234"]["heading"] == "Example program"
    purpose, method = extract_purpose_candidate(found["1234"]["text"])
    assert "shall establish" in purpose
    assert method == "statutory_signal_text"
