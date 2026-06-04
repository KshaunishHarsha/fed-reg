import asyncio
import datetime
from dotenv import load_dotenv

load_dotenv()
from phase_3.db import init_db
from phase_3.digest_query import fetch_digest_rows
from phase_3.digest_builder import build_digest
from phase_3.mail_test import send_test_digest

async def test():
    init_db()
    d = datetime.date(2026,6,1)
    rows = await fetch_digest_rows(d)
    print("Found", len(rows), "rows for", d)
    package = build_digest(rows, d)
    print("A:", package.section_a_count)
    res = send_test_digest(package.html_body, package.text_body, package.digest_date)
    print(res)

if __name__ == "__main__":
    asyncio.run(test())
