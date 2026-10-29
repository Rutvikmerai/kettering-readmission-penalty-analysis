"""
run_sql.py
Runs every query in a .sql file with DuckDB and prints each result.

Run from the project folder:
    python scripts/run_sql.py sql/02_analysis.sql
"""

import re
import sys
import duckdb

sql_file = sys.argv[1] if len(sys.argv) > 1 else "sql/02_analysis.sql"
sql_text = open(sql_file, encoding="utf-8").read()

con = duckdb.connect()

# Split the file into individual statements (skip comment-only chunks)
statements = [s for s in sql_text.split(";") if re.sub(r"--.*", "", s).strip()]

for stmt in statements:
    titles = [line for line in stmt.splitlines() if line.startswith("-- Q")]
    print("\n" + "=" * 80)
    print(titles[-1] if titles else "")
    print("=" * 80)
    print(con.sql(stmt).df().to_string(index=False))
