"""
01_clean_hrrp.py
Cleans the CMS FY 2026 HRRP hospital file and joins hospital details
and the Kettering Health system mapping.

Rules applied here are documented in docs/decision_log.md (D1, D2).

Run from the project folder:
    python scripts/01_clean_hrrp.py

Output:
    data/clean/hrrp_clean.csv   (all U.S. hospitals, one row per hospital x condition)
"""

from pathlib import Path
import pandas as pd

# ---------------------------------------------------------------
# 0. File paths
# ---------------------------------------------------------------
PROJECT = Path(__file__).resolve().parent.parent
RAW = PROJECT / "data" / "raw"
CLEAN = PROJECT / "data" / "clean"
CLEAN.mkdir(parents=True, exist_ok=True)

HRRP_FILE = RAW / "FY_2026_Hospital_Readmissions_Reduction_Program_Hospital.csv"
GENERAL_FILE = RAW / "Hospital_General_Information.csv"
MAPPING_FILE = RAW / "system_mapping.csv"
OUTPUT_FILE = CLEAN / "hrrp_clean.csv"

# ---------------------------------------------------------------
# 1. Load everything as text first (D1: Facility ID must stay text)
# ---------------------------------------------------------------
hrrp = pd.read_csv(HRRP_FILE, dtype=str)
general = pd.read_csv(GENERAL_FILE, dtype=str)
mapping = pd.read_csv(MAPPING_FILE, dtype=str)

print(f"Loaded HRRP: {len(hrrp):,} rows | General info: {len(general):,} rows | Mapping: {len(mapping)} rows")

# ---------------------------------------------------------------
# 2. Rename columns to short, code-friendly names
# ---------------------------------------------------------------
hrrp = hrrp.rename(columns={
    "Facility Name": "facility_name",
    "Facility ID": "facility_id",
    "State": "state",
    "Measure Name": "measure_code",
    "Number of Discharges": "discharges",
    "Footnote": "footnote",
    "Excess Readmission Ratio": "err",
    "Predicted Readmission Rate": "predicted_rate",
    "Expected Readmission Rate": "expected_rate",
    "Number of Readmissions": "readmissions",
    "Start Date": "start_date",
    "End Date": "end_date",
})

# Facility IDs are 6 characters. Pad with leading zeros in case any were shortened.
hrrp["facility_id"] = hrrp["facility_id"].str.strip().str.zfill(6)

# ---------------------------------------------------------------
# 3. Readable condition names
# ---------------------------------------------------------------
CONDITIONS = {
    "READM-30-AMI-HRRP": "AMI (Heart Attack)",
    "READM-30-HF-HRRP": "Heart Failure",
    "READM-30-PN-HRRP": "Pneumonia",
    "READM-30-COPD-HRRP": "COPD",
    "READM-30-CABG-HRRP": "CABG (Bypass Surgery)",
    "READM-30-HIP-KNEE-HRRP": "Hip/Knee Replacement",
}
hrrp["condition"] = hrrp["measure_code"].map(CONDITIONS)

unmapped = hrrp["condition"].isna().sum()
assert unmapped == 0, f"{unmapped} rows have an unknown measure code"

# ---------------------------------------------------------------
# 4. Footnotes (D2)
# ---------------------------------------------------------------
FOOTNOTES = {
    "1": "Too few cases/patients to report",
    "5": "Results not available for this reporting period",
    "7": "No cases met the criteria for this measure",
    "29": "Partial performance period (CMS-approved exception)",
}
hrrp["footnote"] = hrrp["footnote"].str.strip()
hrrp["footnote_desc"] = hrrp["footnote"].map(FOOTNOTES)

# Flag any footnote code we have not documented yet, so nothing slips through silently
unknown_fn = hrrp.loc[hrrp["footnote"].notna() & hrrp["footnote_desc"].isna(), "footnote"].unique()
if len(unknown_fn) > 0:
    print(f"WARNING: undocumented footnote codes found: {list(unknown_fn)}. Add them to D2.")

# D2 rule 4: "Too Few to Report" means the count is hidden for privacy, but ERR is still valid
hrrp["readmissions_suppressed"] = hrrp["readmissions"].str.strip().eq("Too Few to Report")

# D2 rule 3: footnote 29 values are valid but flagged
hrrp["partial_period_flag"] = hrrp["footnote"].eq("29")

# ---------------------------------------------------------------
# 5. Convert text to numbers (D2 rule 5)
#    errors="coerce" turns "Too Few to Report", "N/A", blanks into NaN (null)
# ---------------------------------------------------------------
for col in ["discharges", "err", "predicted_rate", "expected_rate", "readmissions"]:
    hrrp[col] = pd.to_numeric(hrrp[col], errors="coerce")

# D2 rule 1: footnotes 1, 5, 7 have no valid ERR. Force to null even if a value appears.
no_score = hrrp["footnote"].isin(["1", "5", "7"])
hrrp.loc[no_score, ["err", "predicted_rate", "expected_rate"]] = pd.NA

# One flag that later steps use to decide what counts in the analysis
hrrp["err_valid"] = hrrp["err"].notna()

# ---------------------------------------------------------------
# 6. Dates
# ---------------------------------------------------------------
hrrp["start_date"] = pd.to_datetime(hrrp["start_date"], format="%m/%d/%Y", errors="coerce")
hrrp["end_date"] = pd.to_datetime(hrrp["end_date"], format="%m/%d/%Y", errors="coerce")

# ---------------------------------------------------------------
# 7. Join hospital details (city, county, type, ownership)
# ---------------------------------------------------------------
general = general.rename(columns={
    "Facility ID": "facility_id",
    "City/Town": "city",
    "County/Parish": "county",
    "Hospital Type": "hospital_type",
    "Hospital Ownership": "ownership",
})
general["facility_id"] = general["facility_id"].str.strip().str.zfill(6)
general = general[["facility_id", "city", "county", "hospital_type", "ownership"]]

rows_before = len(hrrp)
hrrp = hrrp.merge(general, on="facility_id", how="left")
assert len(hrrp) == rows_before, "Join created duplicate rows; check for repeated Facility IDs"

no_match = hrrp["city"].isna().groupby(hrrp["facility_id"]).first().sum()
print(f"Hospitals with no match in General Information: {no_match}")

# ---------------------------------------------------------------
# 8. Join the health system mapping (D1)
# ---------------------------------------------------------------
mapping = mapping.rename(columns={"Facility ID": "facility_id", "Health System": "health_system"})
mapping["facility_id"] = mapping["facility_id"].str.strip().str.zfill(6)
hrrp = hrrp.merge(mapping[["facility_id", "health_system"]], on="facility_id", how="left")
hrrp["health_system"] = hrrp["health_system"].fillna("Other")

# ---------------------------------------------------------------
# 9. Final column order and save
# ---------------------------------------------------------------
COLUMNS = [
    "facility_id", "facility_name", "health_system", "state", "city", "county",
    "hospital_type", "ownership", "measure_code", "condition",
    "discharges", "readmissions", "readmissions_suppressed",
    "err", "err_valid", "predicted_rate", "expected_rate",
    "footnote", "footnote_desc", "partial_period_flag",
    "start_date", "end_date",
]
hrrp = hrrp[COLUMNS].sort_values(["state", "facility_name", "condition"])
hrrp.to_csv(OUTPUT_FILE, index=False)

# ---------------------------------------------------------------
# 10. Validation summary (check these numbers match the decision log)
# ---------------------------------------------------------------
oh = hrrp[hrrp["state"] == "OH"]
kh = hrrp[hrrp["health_system"] == "Kettering Health"]

print("\n=== VALIDATION ===")
print(f"Total rows saved:            {len(hrrp):,}")
print(f"Ohio rows / hospitals:       {len(oh)} / {oh['facility_id'].nunique()}")
print(f"Ohio rows with valid ERR:    {oh['err_valid'].sum()}")
print(f"Ohio 'Too Few to Report':    {oh['readmissions_suppressed'].sum()}")
print(f"Kettering rows / hospitals:  {len(kh)} / {kh['facility_id'].nunique()}")
print(f"Kettering rows w/ valid ERR: {kh['err_valid'].sum()}")
print(f"Performance period:          {hrrp['start_date'].min().date()} to {hrrp['end_date'].max().date()}")
print("\nOhio footnote counts:")
print(oh["footnote"].fillna("none").value_counts().to_string())
print(f"\nSaved: {OUTPUT_FILE}")
