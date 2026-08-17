"""SEC EDGAR provider behaviour, driven entirely from fixtures.

No test here touches the network. The fixtures are trimmed copies of real
responses, including the awkward parts: a filing whose only line is a tax
withholding, a Form 3 with holdings but no transactions, and the XSL-rendered
``primaryDocument`` path that must be rewritten to reach the machine-readable
original.
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
from urllib.error import HTTPError

import pytest

from app.providers.base import DataUnavailable, RateLimited
from app.providers.sec_edgar import (
    SecEdgarConfigurationError,
    SecEdgarProvider,
    normalize_cik,
    transaction_code_label,
)

USER_AGENT = "Mulmit test admin@example.com"

TICKER_MAP = json.dumps({
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"},
    "2": {"cik_str": None, "ticker": "BROKEN", "title": "No CIK"},
}).encode()

SUBMISSIONS = json.dumps({
    "name": "Apple Inc.",
    "tickers": ["AAPL"],
    "exchanges": ["Nasdaq"],
    "filings": {
        "recent": {
            "form": ["4", "8-K", "4", "3"],
            "accessionNumber": ["0001-26-1", "0002-26-2", "0001-26-3", "0001-26-4"],
            "filingDate": ["2026-08-13", "2026-08-12", "2026-06-17", "2026-01-02"],
            "primaryDocument": [
                "xslF345X06/form4.xml",
                "aapl-8k.htm",
                "xslF345X06/form4.xml",
                "xslF345X02/form3.xml",
            ],
        }
    },
}).encode()

FORM4_SALE = b"""<?xml version="1.0"?>
<ownershipDocument>
  <issuer><issuerCik>0000320193</issuerCik><issuerTradingSymbol>AAPL</issuerTradingSymbol></issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerCik>0001780525</rptOwnerCik><rptOwnerName>Newstead Jennifer</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isOfficer>1</isOfficer><officerTitle>SVP, GC and Secretary</officerTitle></reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2026-08-11</value></transactionDate>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>1439</value></transactionShares>
        <transactionPricePerShare><value>307.75</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts><sharesOwnedFollowingTransaction><value>40107</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
      <ownershipNature><directOrIndirectOwnership><value>D</value></directOrIndirectOwnership></ownershipNature>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>
"""

# A vesting event: the exercise carries no price, and the withheld shares are a
# tax mechanic rather than a decision to sell.
FORM4_VESTING = b"""<?xml version="1.0"?>
<ownershipDocument>
  <issuer><issuerCik>0000320193</issuerCik><issuerTradingSymbol>AAPL</issuerTradingSymbol></issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerCik>0002</rptOwnerCik><rptOwnerName>Borders Ben</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isDirector>1</isDirector><isTenPercentOwner>0</isTenPercentOwner></reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2026-06-15</value></transactionDate>
      <transactionCoding><transactionCode>M</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>30104</value></transactionShares>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2026-06-15</value></transactionDate>
      <transactionCoding><transactionCode>F</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>16238</value></transactionShares>
        <transactionPricePerShare><value>296.42</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
  <derivativeTable>
    <derivativeTransaction>
      <securityTitle><value>Restricted Stock Unit</value></securityTitle>
      <transactionDate><value>2026-06-15</value></transactionDate>
      <transactionCoding><transactionCode>M</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>30104</value></transactionShares>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </derivativeTransaction>
  </derivativeTable>
</ownershipDocument>
"""

# Form 3 states holdings only. It is a valid ownership filing with zero transactions.
FORM3_HOLDING = b"""<?xml version="1.0"?>
<ownershipDocument>
  <issuer><issuerCik>0000320193</issuerCik></issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerCik>0003</rptOwnerCik><rptOwnerName>New Officer</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isOfficer>1</isOfficer><officerTitle>CFO</officerTitle></reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeHolding><securityTitle><value>Common Stock</value></securityTitle></nonDerivativeHolding>
  </nonDerivativeTable>
</ownershipDocument>
"""

ROUTES = {
    "https://www.sec.gov/files/company_tickers.json": TICKER_MAP,
    "https://data.sec.gov/submissions/CIK0000320193.json": SUBMISSIONS,
    "https://www.sec.gov/Archives/edgar/data/320193/0001261/form4.xml": FORM4_SALE,
    "https://www.sec.gov/Archives/edgar/data/320193/0001263/form4.xml": FORM4_VESTING,
    "https://www.sec.gov/Archives/edgar/data/320193/0001264/form3.xml": FORM3_HOLDING,
}


class Transport:
    """Records requests so header and throttling rules can be asserted."""

    def __init__(self, routes=None, failures=None):
        # An explicitly empty route table means "nothing is reachable", which is
        # different from "use the defaults".
        self.routes = dict(ROUTES if routes is None else routes)
        self.failures = list(failures or [])
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        if self.failures:
            failure = self.failures.pop(0)
            if failure is not None:
                raise failure
        try:
            return self.routes[request.full_url]
        except KeyError:
            raise HTTPError(request.full_url, 404, "Not Found", {}, None) from None


def make_provider(transport=None, **kwargs):
    kwargs.setdefault("request_interval", 0.0)
    kwargs.setdefault("retry_backoff", 0.0)
    kwargs.setdefault("sleep", lambda _seconds: None)
    return SecEdgarProvider(USER_AGENT, http_get=transport or Transport(), **kwargs)


def test_user_agent_without_a_contact_address_is_refused():
    with pytest.raises(SecEdgarConfigurationError):
        SecEdgarProvider("Mulmit/1.0")


def test_every_request_declares_contact_and_accepts_compression():
    transport = Transport()
    make_provider(transport).fetch_ticker_map()

    request = transport.requests[0]
    assert request.get_header("User-agent") == USER_AGENT
    assert "gzip" in request.get_header("Accept-encoding")


def test_requests_are_spaced_to_stay_under_the_published_rate_cap():
    clock = {"now": 0.0}
    slept: list[float] = []

    def sleep(seconds):
        slept.append(seconds)
        clock["now"] += seconds

    provider = make_provider(
        Transport(),
        request_interval=0.15,
        sleep=sleep,
        monotonic=lambda: clock["now"],
    )
    provider.fetch_ticker_map()
    provider.fetch_ticker_map()

    # The second call had to wait out the interval; 0.15s spacing is ~6.7 req/s.
    assert slept == [pytest.approx(0.15)]


def test_ticker_map_skips_rows_without_a_cik():
    mapping = make_provider().fetch_ticker_map()

    assert mapping["AAPL"] == ("320193", "Apple Inc.")
    assert "BROKEN" not in mapping


def test_company_parses_ownership_forms_and_skips_other_filings():
    transport = Transport()
    company = make_provider(transport).fetch_company("0000320193")

    assert company.name == "Apple Inc."
    assert company.exchanges == ("Nasdaq",)
    # Three ownership filings; the 8-K is not one of them.
    assert company.filings_seen == 3
    fetched = [request.full_url for request in transport.requests]
    assert not any("8k" in url for url in fetched)
    # The XSL view path must be rewritten to the raw XML beside it.
    assert "https://www.sec.gov/Archives/edgar/data/320193/0001261/form4.xml" in fetched


def test_transactions_keep_each_reported_line_distinct():
    company = make_provider().fetch_company("320193")
    codes = [(item.transaction_code, item.is_derivative) for item in company.transactions]

    assert codes == [("S", False), ("M", False), ("F", False), ("M", True)]
    sale = company.transactions[0]
    assert sale.owner_name == "Newstead Jennifer"
    assert sale.is_officer is True and sale.is_director is False
    assert sale.owner_title == "SVP, GC and Secretary"
    assert sale.transaction_date == dt.date(2026, 8, 11)
    assert sale.filing_date == dt.date(2026, 8, 13)
    assert sale.shares == 1439.0 and sale.price_per_share == 307.75
    assert sale.shares_owned_after == 40107.0

    exercise = company.transactions[1]
    # A grant/exercise has no price. It must stay None rather than becoming zero.
    assert exercise.price_per_share is None
    assert exercise.is_director is True


def test_form3_holding_yields_no_transactions_but_still_counts_as_a_filing():
    company = make_provider().fetch_company("320193")

    assert company.filings_seen == 3
    assert all(item.form_type == "4" for item in company.transactions)


def test_form_limit_bounds_the_request_budget():
    transport = Transport()
    company = make_provider(transport).fetch_company("320193", form_limit=1)

    assert company.filings_seen == 1
    # One submissions call plus exactly one filing document.
    assert len(transport.requests) == 2


def test_one_unreadable_filing_does_not_discard_the_rest():
    routes = dict(ROUTES)
    routes.pop("https://www.sec.gov/Archives/edgar/data/320193/0001263/form4.xml")
    company = make_provider(Transport(routes)).fetch_company("320193")

    assert [item.transaction_code for item in company.transactions] == ["S"]


def test_fair_access_block_is_reported_as_rate_limited_not_a_failure():
    blocked = HTTPError("https://www.sec.gov/files/company_tickers.json", 403, "Forbidden", {}, None)
    provider = make_provider(Transport(failures=[blocked, blocked, blocked]), retries=2)

    with pytest.raises(RateLimited):
        provider.fetch_ticker_map()


def test_transient_server_error_is_retried_then_succeeds():
    transport = Transport(failures=[HTTPError("u", 503, "busy", {}, None), None])
    mapping = make_provider(transport, retries=2).fetch_ticker_map()

    assert mapping["NVDA"] == ("1045810", "NVIDIA CORP")
    assert len(transport.requests) == 2


def test_missing_document_is_unavailable_rather_than_retried_forever():
    transport = Transport(routes={})
    provider = make_provider(transport, retries=3)

    with pytest.raises(DataUnavailable):
        provider.fetch_ticker_map()
    assert len(transport.requests) == 1  # 404 is final


def test_malformed_payloads_are_rejected():
    with pytest.raises(DataUnavailable):
        make_provider(Transport({"https://www.sec.gov/files/company_tickers.json": b"{"})).fetch_ticker_map()

    routes = dict(ROUTES)
    routes["https://www.sec.gov/Archives/edgar/data/320193/0001261/form4.xml"] = b"<not-xml"
    company = make_provider(Transport(routes)).fetch_company("320193")
    assert [item.transaction_code for item in company.transactions] == ["M", "F", "M"]


def test_gzipped_bodies_survive_the_default_transport(monkeypatch):
    """The requests advertise compression, so the transport must unwrap it."""
    import app.providers.sec_edgar as module

    class Response:
        headers = {"Content-Encoding": "gzip"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return gzip.compress(TICKER_MAP)

    monkeypatch.setattr(module, "urlopen", lambda *_a, **_k: Response())
    provider = SecEdgarProvider(USER_AGENT, request_interval=0.0)

    assert provider.fetch_ticker_map()["AAPL"][0] == "320193"


def test_cik_normalisation_and_code_labels():
    assert normalize_cik("0000320193") == "320193"
    assert normalize_cik(320193) == "320193"
    with pytest.raises(DataUnavailable):
        normalize_cik("nope")

    assert transaction_code_label("P")["en"].startswith("Open-market")
    assert transaction_code_label("ZZ")["en"] == "Code ZZ"


def test_the_stored_filing_link_is_the_human_view_not_the_parser_input():
    """Raw form XML renders as an unstyled document tree in a browser."""
    import datetime as dt

    calls = []
    body = (
        b'<?xml version="1.0"?><ownershipDocument><reportingOwner>'
        b"<reportingOwnerId><rptOwnerName>A</rptOwnerName>"
        b"<rptOwnerCik>1</rptOwnerCik></reportingOwnerId></reportingOwner>"
        b"<nonDerivativeTable><nonDerivativeTransaction>"
        b"<securityTitle><value>Common Stock</value></securityTitle>"
        b"<transactionDate><value>2026-08-11</value></transactionDate>"
        b"<transactionCoding><transactionCode>S</transactionCode></transactionCoding>"
        b"<transactionAmounts><transactionShares><value>10</value></transactionShares>"
        b"<transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>"
        b"</transactionAmounts></nonDerivativeTransaction></nonDerivativeTable>"
        b"</ownershipDocument>"
    )

    def http(request, timeout):
        calls.append(request.full_url)
        return body

    def provider():
        return SecEdgarProvider(
            "Mulmit test admin@example.com", http_get=http, retries=0,
            request_interval=0.0, sleep=lambda _s: None,
        )

    # EDGAR points primaryDocument at the XSL-rendered view; the parser reads
    # the raw twin but the stored link keeps the styled path.
    rows = provider().fetch_ownership_document(
        "320193", "0001140361-26-032884", "xslF345X06/form4.xml",
        form_type="4", filing_date=dt.date(2026, 8, 13),
    )
    assert calls[-1].endswith("/000114036126032884/form4.xml")
    assert rows[0].filing_url.endswith("/000114036126032884/xslF345X06/form4.xml")

    # A filing with no styled twin links the index page, never the raw XML.
    rows = provider().fetch_ownership_document(
        "320193", "0001140361-26-032884", "form4.xml",
        form_type="4", filing_date=dt.date(2026, 8, 13),
    )
    assert rows[0].filing_url.endswith("/000114036126032884/0001140361-26-032884-index.htm")
