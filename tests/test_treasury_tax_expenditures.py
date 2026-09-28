from io import BytesIO

import pandas as pd

from federalgraph.extract.treasury_tax_expenditures import records_from_workbook


def test_treasury_workbook_extracts_numbered_identity_rows():
    buf = BytesIO()
    frame = pd.DataFrame(
        [
            ["National Defense", None, None],
            [1, "Exclusion of benefits to armed forces personnel", 100],
            ["Education", None, None],
            [2, "Credit for education expenses", 200],
        ]
    )
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, header=False, sheet_name="Table 1")
    rows = records_from_workbook(buf.getvalue(), 2027, "https://example.test/tax.xlsx")
    assert [r["source_record_id"] for r in rows] == ["FY2027:1", "FY2027:2"]
    assert rows[0]["function_raw"] == "National Defense"
    assert rows[1]["function_raw"] == "Education"
