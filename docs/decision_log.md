# Decision Log - Ohio Readmissions Project

## D1. Health system scope: Kettering Health (7 CMS facility IDs)

**Decision:** Kettering Health is analyzed as 7 facilities, matched by CMS Facility ID (CCN).

**Why only 7 when Kettering lists 14-15 locations:** Kettering Health's website lists 15 facilities, but several are marked "a service of" a larger campus. These satellite campuses bill Medicare under the parent hospital's ID, so their readmissions are already included in the parent's numbers. I confirmed none of them appear as separate hospitals in the CMS Hospital General Information file.

| Satellite campus | Reported under |
|---|---|
| Washington Township (former Southview), Huber, Preble | Kettering Health Dayton (360133) |
| Middletown | Kettering Health Main Campus (360079) |
| Franklin | Kettering Health Miamisburg (360239) |
| Springfield, Wilmington | Soin Medical Center (360360) |

**Excluded:** Kettering Health Behavioral Medical Center (Moraine). It is a psychiatric facility and not part of HRRP.

**Name differences:** CMS still lists Kettering Health Hamilton under its old name, "Fort Hamilton Hughes Memorial Hospital" (360132). Soin Medical Center does not have "Kettering" in its CMS name. Matching is done on Facility ID, not name, to avoid missing these.

**Data type note:** Facility ID must be stored as text, not a number. Some CMS IDs contain letters (example: Dayton VA Medical Center is 36007F), and converting to numbers would break joins.

**Risk / limitation:** Because satellite campuses roll up into parent IDs, results for a "hospital" in this analysis may reflect several physical sites. A recommendation to Kettering should be framed at the CCN level.

**Source:** ketteringhealth.org/name/ (checked 2026-10-26); CMS Hospital General Information file.

## D2. Handling footnotes and missing values

**Footnote meanings (CMS Hospital Compare footnote definitions):**

| Code | Meaning | Ohio rows | Kettering rows | What the row contains |
|---|---|---|---|---|
| 1 | Number of cases/patients is too few to report | 113 | 8 | No ERR, no discharges, no readmissions |
| 5 | Results are not available for this reporting period | 110 | 7 | No ERR, no discharges, no readmissions |
| 7 | No cases met the criteria for this measure | 4 | 0 | Discharges present, no ERR |
| 29 | Calculated using partial performance period data due to a CMS-approved exception | 4 | 0 | Full ERR and counts present |
| (none) | Normal result | 477 | 27 | ERR present (see note on "Too Few to Report" below) |

**Handling rules:**

1. **Footnotes 1, 5, 7: keep the row, set ERR to null, exclude from all ERR averages and penalty calculations.** These are not zeros. Treating a missing ERR as 0 would make a hospital look like it had no readmissions. The rows stay in the clean table so the data shows which conditions each hospital could not be measured on.
2. **Footnote 5 is often a CABG or hip/knee row at a smaller hospital**, likely because the hospital does not perform enough (or any) of that procedure. This is a working assumption, not confirmed by CMS, so it is labeled as an assumption in the README.
3. **Footnote 29: keep the ERR, add a flag column (`partial_period_flag = TRUE`).** The value is valid but based on less data, so it is called out in any chart that shows it. No Kettering rows are affected.
4. **"Too Few to Report" in Number of Readmissions (123 Ohio rows, no footnote): keep the ERR, set readmission count and discharges to null.** CMS hides small counts for patient privacy, but the ERR is still published and valid. These rows are used in ERR analysis but not in any calculation that needs raw counts. Kettering examples: Greene Memorial pneumonia, Dayton hip/knee, Troy COPD.
5. **All numeric columns are converted from text to numbers after these rules run**, using a conversion that turns non-numeric text into null instead of failing.

**Result for Kettering:** 42 rows (7 hospitals x 6 conditions). 27 have a usable ERR. 15 are excluded from ERR analysis (8 with footnote 1, 7 with footnote 5).

**Why it matters:** The penalty math only uses conditions with a valid ERR. Knowing which rows are "not measured" vs. "measured but small" prevents both undercounting and false precision.

**Source:** CMS Hospital Compare footnote definitions (as published by American Hospital Directory, ahd.com); FY 2026 HRRP Hospital file.

## D3. Hospitals in HRRP but missing from Hospital General Information

**Finding:** 20 hospitals (all outside Ohio) appear in the FY 2026 HRRP file but not in the current Hospital General Information file. These are likely hospitals that closed, merged, or changed their CMS ID after the 2021-2024 performance period.

**Decision:** Keep them. Their city, county, type, and ownership are left blank. They still count in national comparisons because CMS included them when calculating peer medians. No Ohio or Kettering hospitals are affected.

## D4. Keep all U.S. hospitals in the clean file

**Decision:** The clean file keeps all states, not just Ohio. HRRP penalties are based on comparing each hospital to a national peer group, so later steps need national data to calculate benchmarks. Filters for Ohio and Kettering are applied in the analysis, not during cleaning.

## D5. Use the FY 2027 Supplemental File for the penalty analysis

**Decision:** The penalty analysis uses the FY 2027 HRRP Supplemental Data File (FY 2027 IPPS/LTCH PPS Final Rule), not the FY 2026 Provider Data Catalog file.

**Why:**
- It is the penalty in effect now (applies to discharges from October 1, 2026).
- It contains every input to the CMS formula: peer group, peer group median ERR, DRG payment ratio, neutrality modifier, and the official payment reduction.
- It uses the newer method: a 2-year period (July 1, 2023 to June 30, 2025) and both Medicare FFS and Medicare Advantage patients.

**The FY 2026 file (Stages 2-3) is kept** for the earlier performance view and the SQL analysis. The two years are not directly comparable because the method changed. Any comparison is labeled that way.

**Cleaning rules for this file:**
- Headers are on row 2 (row 1 is a title).
- "." means not available and is read as missing.
- The "End of worksheet" footer row is removed by keeping only 6-character CCNs.

## D6. Rebuilt the CMS penalty formula and validated it

**Formula used:**
payment reduction = min(3%, neutrality modifier x SUM over penalized measures of DRG payment ratio x (ERR - peer group median ERR))

A measure is penalized only when the penalty indicator is "Y" (25+ eligible discharges and ERR above the peer group median).

**Validation:** The rebuilt reduction matches CMS's published payment reduction percentage (within 4-decimal rounding) for 2,912 of 2,912 hospitals (100%). This confirms the condition-level breakdown is CMS's own math, not an approximation.

**Limitation:** "Share of system total" adds percentage points across hospitals without weighting by each hospital's Medicare payments. A 0.5-point penalty at a large hospital costs more dollars than at a small one. The dollar step (next stage) corrects for this.

## D7. Penalty dollar estimate method

**Data:** CMS "Medicare Inpatient Hospitals - by Provider," data year 2024 (file mup_inp_ry26_p04_v10_dy24_prv.csv). Column used: `Tot_Mdcr_Pymt_Amt` (total Medicare payments).

**Check:** 2024 discharge counts in this file are within about 5% of CMS's FY 2024 case counts in the HRRP Supplemental File for all 7 Kettering hospitals (median ratio across U.S. hospitals = 1.00). The file covers essentially all Medicare FFS stays.

**Cleaning:** The export drops leading zeros from some CCNs (557 rows have 5 digits). CCNs are padded back to 6 characters before joining. 20 hospitals in the penalty file have no 2024 payment data (none in Kettering).

**Method:**
- The HRRP penalty applies only to Medicare FFS base operating DRG payments. The public file reports total Medicare payments, which also include add-ons (teaching, safety-net, outlier, capital).
- Base payments are shown as a range: low = 70% of total (assumption), high = 100% of total (ceiling).
- Estimated penalty $ = CMS payment reduction % x estimated base payments.
- 2024 payments stand in for FY 2027 volume.
- Condition dollars = hospital penalty $ x that condition's share of the hospital's penalty. Valid because no Kettering hospital hits the 3% cap.

**Every dollar figure is labeled "estimate."** The 70% figure is an assumption, not a CMS number. A hospital's finance team could replace it with the actual base DRG amount from its own records or Hospital-Specific Report.
