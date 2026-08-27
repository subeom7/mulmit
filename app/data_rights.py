"""Serving-side rights gates for every public data lane.

Reachable is not the same as redistributable. ``FRED_ENABLED=false`` used to
stop ingestion only, so a database that had been seeded earlier kept serving
FRED-derived numbers from the request path. Every public lane now asks here
before a stored value may leave the process.

The gate is per provider lane on purpose. Closing the FRED lane must not block
an approved New York Fed lane that lands later, and an unregistered provider id
must never resolve to "allowed" — adding a lane is a deliberate edit here, not
a side effect of writing rows into the database.
"""

from __future__ import annotations

from collections.abc import Callable

from . import config

# --- lane identifiers --------------------------------------------------------
FRED = "fred"
HYPERLIQUID_HIP3 = "hyperliquid_hip3"
LEGACY_PRICE_DATA = "legacy_price_data"
SEC_EDGAR = "sec_edgar"
DART = "dart"
NYFED = "nyfed"
FEDBOARD = "federal_reserve"
BLS = "bls"
FSC = "fsc"
ECOS = "ecos"
CRYPTO = "crypto"
ALTERNATIVE_ME = "alternative_me"
COINMARKETCAP = "coinmarketcap"
UPBIT = "upbit"
CHAIN_GAS = "chain_gas"
BIO = "bio"
CLINICALTRIALS = "clinicaltrials"
OPENFDA = "openfda"
PUBMED = "pubmed"
FEDERAL_REGISTER = "federal_register"
MFDS = "mfds_drug_permit"
OFR = "ofr"
NPS_PORTFOLIO = "nps_portfolio"

# --- structured client contracts --------------------------------------------
# The frontend keys off ``code``: these are disabled states, not retryable
# errors, so it must not offer "refresh and try again".
MACRO_DATA_DISABLED = {
    "code": "macro_data_disabled",
    "status": "disabled",
    "message": (
        "No approved macro data source is enabled. Stored values from disabled "
        "providers are withheld from the public API."
    ),
}

HIP3_PENDING_RIGHTS = {
    "code": "hip3_public_display_pending_rights",
    "status": "pending_rights",
    "message": (
        "Public display rights for Hyperliquid HIP-3 / trade.xyz data are not "
        "confirmed in writing, so Mulmit withholds the values."
    ),
}

INSIDER_DATA_DISABLED = {
    "code": "insider_data_disabled",
    "status": "disabled",
    "message": "SEC EDGAR insider-filing collection is disabled for this deployment.",
}

INSIDER_NOT_CONFIGURED = {
    "code": "insider_data_not_configured",
    "status": "not_configured",
    "message": (
        "SEC_EDGAR_USER_AGENT must declare a contact address before EDGAR may be "
        "queried, as required by the SEC fair-access policy."
    ),
}

KR_STOCK_DISABLED = {
    "code": "kr_stock_data_disabled",
    "status": "disabled",
    "message": (
        "The FSC open-data lane is disabled for this deployment, so Korean "
        "listing search and per-stock analysis are withheld."
    ),
}

KR_INSIDER_DISABLED = {
    "code": "kr_insider_data_disabled",
    "status": "disabled",
    "message": "DART insider-report relay is disabled for this deployment.",
}

KR_INSIDER_NOT_CONFIGURED = {
    "code": "kr_insider_not_configured",
    "status": "not_configured",
    "message": "DART_API_KEY must be issued by opendart.fss.or.kr before use.",
}

KR_SEARCH_INTEREST_DISABLED = {
    "code": "kr_search_interest_disabled",
    "status": "disabled",
    "message": (
        "The NAVER DataLab search-trend lane is disabled for this deployment "
        "(gate off or client credentials missing)."
    ),
}

KR_PENSION_DISABLED = {
    "code": "kr_pension_data_disabled",
    "status": "disabled",
    "message": "DART pension-filing relay is disabled for this deployment.",
}

KR_PENSION_NOT_CONFIGURED = {
    "code": "kr_pension_not_configured",
    "status": "not_configured",
    "message": "DART_API_KEY must be issued by opendart.fss.or.kr before use.",
}

# 채점 lane은 DART(이벤트)와 FSC(가격) 두 승인 lane의 합성이다 — 어느 한쪽이
# 꺼져도 닫힌다. 새 권리는 없다(docs/PLAN_SCORING.md).
KR_SCORING_DISABLED = {
    "code": "kr_scoring_disabled",
    "status": "disabled",
    "message": "The scoring lane needs both the DART and FSC lanes enabled.",
}

KR_SCORING_NOT_CONFIGURED = {
    "code": "kr_scoring_not_configured",
    "status": "not_configured",
    "message": "DART_API_KEY and FSC_API_KEY must both be configured before use.",
}

KR_FUNDAMENTALS_DISABLED = {
    "code": "kr_fundamentals_disabled",
    "status": "disabled",
    "message": "DART financial-statement relay is disabled for this deployment.",
}

KR_FUNDAMENTALS_NOT_CONFIGURED = {
    "code": "kr_fundamentals_not_configured",
    "status": "not_configured",
    "message": "DART_API_KEY must be issued by opendart.fss.or.kr before use.",
}

US_FUNDAMENTALS_DISABLED = {
    "code": "us_fundamentals_disabled",
    "status": "disabled",
    "message": "The SEC EDGAR lane is disabled for this deployment.",
}

US_FUNDAMENTALS_NOT_CONFIGURED = {
    "code": "us_fundamentals_not_configured",
    "status": "not_configured",
    "message": "SEC_EDGAR_USER_AGENT must declare a contact before EDGAR use.",
}

US_MANAGERS_DISABLED = {
    "code": "us_managers_disabled",
    "status": "disabled",
    "message": "The SEC EDGAR lane is disabled for this deployment.",
}

US_MANAGERS_NOT_CONFIGURED = {
    "code": "us_managers_not_configured",
    "status": "not_configured",
    "message": "SEC_EDGAR_USER_AGENT must declare a contact before EDGAR use.",
}

CRYPTO_SECTION_DISABLED = {
    "code": "crypto_section_disabled",
    "status": "disabled",
    "message": "The crypto section is not enabled for this deployment.",
}

CRYPTO_SENTIMENT_DISABLED = {
    "code": "crypto_sentiment_disabled",
    "status": "disabled",
    "message": "The alternative.me Crypto Fear & Greed relay is disabled for this deployment.",
}

CRYPTO_SENTIMENT_COLLECTING = {
    "code": "crypto_sentiment_collecting",
    "status": "collecting",
    "message": (
        "The Crypto Fear & Greed relay is enabled but has not stored its first "
        "observation yet; values appear after the next ingest pass."
    ),
}

CRYPTO_STRUCTURE_DISABLED = {
    "code": "crypto_structure_disabled",
    "status": "disabled",
    "message": "The CoinMarketCap global-metrics relay is disabled for this deployment.",
}

CRYPTO_STRUCTURE_COLLECTING = {
    "code": "crypto_structure_collecting",
    "status": "collecting",
    "message": (
        "The CoinMarketCap relay is enabled but has not stored its first observation "
        "yet (or the ingest key is missing); values appear after the next ingest pass."
    ),
}

BIO_SECTION_DISABLED = {
    "code": "bio_section_disabled",
    "status": "disabled",
    "message": "The bio section is not enabled for this deployment.",
}

BIO_TRIALS_DISABLED = {
    "code": "bio_trials_disabled",
    "status": "disabled",
    "message": "The ClinicalTrials.gov watchlist relay is disabled for this deployment.",
}

BIO_TRIALS_COLLECTING = {
    "code": "bio_trials_collecting",
    "status": "collecting",
    "message": (
        "The ClinicalTrials.gov relay is enabled but has not stored its first pass yet; "
        "values appear after the next ingest run."
    ),
}

BIO_FDA_DISABLED = {
    "code": "bio_fda_disabled",
    "status": "disabled",
    "message": "The openFDA approvals relay is disabled for this deployment.",
}

BIO_FDA_COLLECTING = {
    "code": "bio_fda_collecting",
    "status": "collecting",
    "message": (
        "The openFDA relay is enabled but has not stored its first pass yet; "
        "values appear after the next ingest run."
    ),
}

BIO_ADCOMM_DISABLED = {
    "code": "bio_adcomm_disabled",
    "status": "disabled",
    "message": "The Federal Register advisory-committee relay is disabled for this deployment.",
}

BIO_ADCOMM_COLLECTING = {
    "code": "bio_adcomm_collecting",
    "status": "collecting",
    "message": (
        "The Federal Register relay is enabled but has not stored its first pass yet; "
        "values appear after the next ingest run."
    ),
}

BIO_MFDS_DISABLED = {
    "code": "bio_mfds_disabled",
    "status": "disabled",
    "message": "The MFDS drug-permit relay is disabled for this deployment.",
}

BIO_MFDS_COLLECTING = {
    "code": "bio_mfds_collecting",
    "status": "collecting",
    "message": (
        "The MFDS relay is enabled but has not stored its first pass yet (or the ingest key is missing); "
        "values appear after the next ingest run."
    ),
}

# 허가 이벤트 채점 보드는 mfds(원천)와 FSC(가격)의 합성이다 — 어느 한쪽이
# 꺼져도 닫힌다. 새 권리는 없다(둘 다 기존 승인 lane).
BIO_OUTCOMES_DISABLED = {
    "code": "bio_outcomes_disabled",
    "status": "disabled",
    "message": "The permit-outcome board needs both the MFDS and FSC lanes enabled.",
}

BIO_OUTCOMES_COLLECTING = {
    "code": "bio_outcomes_collecting",
    "status": "collecting",
    "message": "The permit-outcome board has not stored its first pass yet; values appear after the next ingest run.",
}

CHAIN_GAS_DISABLED = {
    "code": "chain_gas_disabled",
    "status": "disabled",
    "message": "The gas/fee strip is disabled for this deployment.",
}

CHAIN_GAS_NOT_CONFIGURED = {
    "code": "chain_gas_not_configured",
    "status": "not_configured",
    "message": (
        "The gas/fee strip is switched on but no CHAIN_RPC_*_URL is set; the operator's "
        "RPC-provider endpoint must be configured before any chain is read."
    ),
}

UPBIT_PENDING_RIGHTS = {
    "code": "upbit_quotation_pending_rights",
    "status": "pending_rights",
    "message": (
        "Upbit quotation relay is withheld until public-display rights are confirmed in "
        "writing or the operator records a risk acceptance (register §3.19)."
    ),
}

US_PTR_DISABLED = {
    "code": "us_ptr_disabled",
    "status": "disabled",
    "message": "The House PTR relay is disabled for this deployment.",
}

NO_STORE_HEADERS = {"Cache-Control": "no-store"}

# Macro lanes and the flag that decides whether their stored rows may be served.
# Flags are read through ``config`` at call time so tests and a restart-free
# rollback both take effect immediately.
_MACRO_LANES: dict[str, Callable[[], bool]] = {
    FRED: lambda: config.FRED_ENABLED,
    NYFED: lambda: config.NYFED_ENABLED,
    FEDBOARD: lambda: config.FEDBOARD_ENABLED,
    BLS: lambda: config.BLS_ENABLED,
    FSC: lambda: config.FSC_ENABLED,
    ECOS: lambda: config.ECOS_ENABLED,
    OFR: lambda: config.OFR_ENABLED,
}

# Named rather than derived from the lane id. A provider id and its environment
# variable do not always match, and /api/status telling an operator to set a
# variable that does not exist is worse than saying nothing.
_MACRO_LANE_GATES = {
    FRED: "FRED_ENABLED",
    NYFED: "NYFED_ENABLED",
    FEDBOARD: "FEDBOARD_ENABLED",
    BLS: "BLS_ENABLED",
    FSC: "FSC_ENABLED",
    ECOS: "ECOS_ENABLED",
    OFR: "OFR_ENABLED",
}


# Row-level verdicts stored on ``economic_series.rights_status``. Only one of
# them permits publishing values; everything else, including an unrecognised
# string, withholds them.
SERVABLE_ROW_RIGHTS = "approved"


def macro_lane_enabled(provider_id: str) -> bool:
    """Fail closed for any lane that has not been registered above."""
    gate = _MACRO_LANES.get(provider_id)
    return bool(gate()) if gate is not None else False


def series_values_servable(provider_id: str, rights_status: str | None) -> bool:
    """Both gates must agree before a stored observation may be published.

    The lane answers "may this provider be served at all"; the row answers "may
    this particular series be". They are different questions: FRED's VIXCLS
    carries Cboe's rights, so it stays withheld even when the FRED lane is open.
    """
    return macro_lane_enabled(provider_id) and rights_status == SERVABLE_ROW_RIGHTS


def enabled_macro_lanes() -> list[str]:
    return [provider_id for provider_id in _MACRO_LANES if macro_lane_enabled(provider_id)]


def macro_serving_enabled() -> bool:
    return bool(enabled_macro_lanes())


def hip3_public_display_enabled() -> bool:
    return bool(config.HIP3_PUBLIC_DISPLAY_ENABLED)


def hip3_history_enabled() -> bool:
    """Stored HIP-3 history needs its own opt-in on top of the display gate."""
    return bool(config.HIP3_HISTORY_ENABLED) and hip3_public_display_enabled()


def crypto_section_enabled() -> bool:
    """The crypto page and /api/crypto/* are a deliberate rollout, not a side effect."""
    return bool(config.CRYPTO_SECTION_ENABLED)


def crypto_overview_enabled() -> bool:
    """Hyperliquid native perps share the HIP-3 display gate and posture."""
    return crypto_section_enabled() and hip3_public_display_enabled()


def alternative_me_serving_enabled() -> bool:
    """The alternative.me relay is its own lane under the section switch."""
    return crypto_section_enabled() and bool(config.ALTERNATIVE_ME_ENABLED)


def cmc_serving_enabled() -> bool:
    """Web serves the stored CoinMarketCap blob once the operator switched the lane on."""
    return crypto_section_enabled() and bool(config.CMC_ENABLED)


def cmc_ingest_enabled() -> bool:
    """Only ingest holds the key; without it the lane is switched on but cannot fetch."""
    return cmc_serving_enabled() and bool(config.CMC_API_KEY)


def cmc_status() -> str:
    """Serving state only — the key lives in the ingest process, so a web worker
    without it is not "not configured"; it simply never fetches."""
    return "enabled" if cmc_serving_enabled() else "disabled"


def coinalyze_serving_enabled() -> bool:
    """Web serves the stored Coinalyze blob once the operator switched the lane on."""
    return crypto_section_enabled() and bool(config.COINALYZE_ENABLED)


def coinalyze_ingest_enabled() -> bool:
    """Only ingest holds the key; without it the lane is on but never fetches."""
    return coinalyze_serving_enabled() and bool(config.COINALYZE_API_KEY)


def upbit_serving_enabled() -> bool:
    """Upbit quotes stay withheld (`pending_rights`) until the operator opens the gate."""
    return crypto_section_enabled() and bool(config.UPBIT_ENABLED)


def kr_search_interest_enabled() -> bool:
    """검색 관심도는 게이트와 키가 **둘 다** 있어야 열린다.

    권리는 정리됐지만(등록부 §6.7) 키 없이 켜면 매 요청이 인증 실패로 끝난다 —
    그건 "데이터 없음"이 아니라 고장이고, 화면에 그렇게 보이면 안 된다.
    """
    return bool(
        config.NAVER_DATALAB_ENABLED
        and config.NAVER_DATALAB_CLIENT_ID
        and config.NAVER_DATALAB_CLIENT_SECRET
    )


def bio_section_enabled() -> bool:
    """The bio page and its lanes are a deliberate rollout behind one switch."""
    return bool(config.BIO_SECTION_ENABLED)


def clinicaltrials_serving_enabled() -> bool:
    return bio_section_enabled() and bool(config.CLINICALTRIALS_ENABLED)


def clinicaltrials_ingest_enabled() -> bool:
    """Unkeyed public API — the same switch governs fetching and serving."""
    return clinicaltrials_serving_enabled()


def openfda_serving_enabled() -> bool:
    return bio_section_enabled() and bool(config.OPENFDA_ENABLED)


def openfda_ingest_enabled() -> bool:
    """The openFDA key is optional; without it the per-IP allowance covers our few daily calls."""
    return openfda_serving_enabled()


def pubmed_serving_enabled() -> bool:
    """PubMed citations ride the trials lane: both switches must be on."""
    return clinicaltrials_serving_enabled() and bool(config.PUBMED_ENABLED)


def pubmed_ingest_enabled() -> bool:
    return pubmed_serving_enabled()


def federal_register_serving_enabled() -> bool:
    return bio_section_enabled() and bool(config.FEDERAL_REGISTER_ENABLED)


def federal_register_ingest_enabled() -> bool:
    return federal_register_serving_enabled()


def mfds_serving_enabled() -> bool:
    return bio_section_enabled() and bool(config.MFDS_ENABLED)


def mfds_ingest_enabled() -> bool:
    """Only ingest holds the data.go.kr key (MFDS_API_KEY, falling back to FSC_API_KEY)."""
    return mfds_serving_enabled() and bool(config.MFDS_API_KEY)


def nps_portfolio_serving_enabled() -> bool:
    """국민연금 국내주식 포트폴리오. **언제나 열려 있고, 그 사실이 여기 적혀
    있는 것이 요점이다.**

    이 lane에는 환경 게이트가 없다. 다른 lane과 달리 요청 시 외부를 부르지
    않고(파일이 이미지 안에 있다) 이용허락범위가 "제한 없음"이라 막아야 할
    권리 문제도 없다 — 끌 수 없는 게이트는 안전을 더하지 않고 고장날 곳만
    만든다. 그렇다고 이 모듈을 건너뛰면 "모든 공개 lane은 여기에 묻는다"는
    성질이 조용히 깨지므로, 판단을 상수로 두는 대신 함수로 세워 둔다.

    닫아야 할 날이 오면(원천이 라이선스를 바꾸는 등) 고칠 곳은 여기 한 곳이다.
    사정은 `docs/DATA_SOURCE_REGISTER.md` §3.30.
    """
    return True


def chain_gas_configured_chains() -> list[str]:
    return [
        name
        for name, value in (
            ("ethereum", config.CHAIN_RPC_ETHEREUM_URL),
            ("base", config.CHAIN_RPC_BASE_URL),
            ("arbitrum", config.CHAIN_RPC_ARBITRUM_URL),
        )
        if value
    ]


def chain_gas_serving_enabled() -> bool:
    """Gas strip: section switch + its own switch + at least one operator RPC URL."""
    return crypto_section_enabled() and bool(config.CHAIN_GAS_ENABLED) and bool(chain_gas_configured_chains())


def chain_gas_status() -> str:
    if not (crypto_section_enabled() and config.CHAIN_GAS_ENABLED):
        return "disabled"
    return "enabled" if chain_gas_configured_chains() else "not_configured"


def dart_serving_enabled() -> bool:
    """The issued key is part of the permission: DART meters by key."""
    return bool(config.DART_ENABLED and config.DART_API_KEY)


def dart_status() -> str:
    if not config.DART_ENABLED:
        return "disabled"
    return "enabled" if config.DART_API_KEY else "not_configured"


def sec_edgar_serving_enabled() -> bool:
    """A declared contact address is part of the permission, not a nicety.

    The SEC's fair-access policy treats an undeclared automated client as an
    unclassified bot, so an unset ``SEC_EDGAR_USER_AGENT`` closes the lane even
    when the operator switched it on.
    """
    return bool(config.SEC_EDGAR_ENABLED and config.SEC_EDGAR_USER_AGENT)


def sec_edgar_status() -> str:
    if not config.SEC_EDGAR_ENABLED:
        return "disabled"
    return "enabled" if config.SEC_EDGAR_USER_AGENT else "not_configured"


def lane_report() -> dict[str, dict[str, str]]:
    """Operator-facing lane summary for ``/api/status``."""
    report: dict[str, dict[str, str]] = {
        LEGACY_PRICE_DATA: {
            "status": "enabled" if config.LEGACY_PRICE_DATA_ENABLED else "disabled",
            "gate": "LEGACY_PRICE_DATA_ENABLED",
        },
        HYPERLIQUID_HIP3: {
            "status": "enabled" if hip3_public_display_enabled() else "pending_rights",
            "gate": "HIP3_PUBLIC_DISPLAY_ENABLED",
            "history": "enabled" if hip3_history_enabled() else "withheld",
            "history_gate": "HIP3_HISTORY_ENABLED",
        },
        SEC_EDGAR: {
            "status": sec_edgar_status(),
            "gate": "SEC_EDGAR_ENABLED + SEC_EDGAR_USER_AGENT",
        },
        DART: {
            "status": dart_status(),
            "gate": "DART_ENABLED + DART_API_KEY",
        },
        CRYPTO: {
            "status": "enabled" if crypto_section_enabled() else "disabled",
            "gate": "CRYPTO_SECTION_ENABLED",
            "overview": "enabled" if crypto_overview_enabled() else "withheld",
            "overview_gate": "CRYPTO_SECTION_ENABLED + HIP3_PUBLIC_DISPLAY_ENABLED",
        },
        ALTERNATIVE_ME: {
            "status": "enabled" if alternative_me_serving_enabled() else "disabled",
            "gate": "CRYPTO_SECTION_ENABLED + ALTERNATIVE_ME_ENABLED",
        },
        COINMARKETCAP: {
            "status": cmc_status(),
            "gate": "CRYPTO_SECTION_ENABLED + CMC_ENABLED",
            "fetch_key": "present" if config.CMC_API_KEY else "absent_in_this_process",
            "fetch_gate": "CMC_API_KEY (ingest only)",
            "endpoints": ["global-metrics/quotes/latest", "cryptocurrency/quotes/latest (USDT, USDC supply)"],
        },
        UPBIT: {
            "status": "enabled" if upbit_serving_enabled() else "pending_rights",
            "gate": "CRYPTO_SECTION_ENABLED + UPBIT_ENABLED",
        },
        BIO: {
            "status": "enabled" if bio_section_enabled() else "disabled",
            "gate": "BIO_SECTION_ENABLED",
        },
        CLINICALTRIALS: {
            "status": "enabled" if clinicaltrials_serving_enabled() else "disabled",
            "gate": "BIO_SECTION_ENABLED + CLINICALTRIALS_ENABLED",
            "display_duties": "attribution, currency, processed date, modifications stated (Terms 2023-01-31)",
        },
        OPENFDA: {
            "status": "enabled" if openfda_serving_enabled() else "disabled",
            "gate": "BIO_SECTION_ENABLED + OPENFDA_ENABLED",
            "fetch_key": "present" if config.OPENFDA_API_KEY else "absent_optional",
            "license": "public domain, CC0 1.0",
        },
        PUBMED: {
            "status": "enabled" if pubmed_serving_enabled() else "disabled",
            "gate": "BIO_SECTION_ENABLED + CLINICALTRIALS_ENABLED + PUBMED_ENABLED",
            "policy": "metadata only; tool/email identified; 3 req/s; off-peak window",
            "fetch_key": "present" if config.NCBI_API_KEY else "absent_optional",
        },
        FEDERAL_REGISTER: {
            "status": "enabled" if federal_register_serving_enabled() else "disabled",
            "gate": "BIO_SECTION_ENABLED + FEDERAL_REGISTER_ENABLED",
            "restriction": "no NARA/OFR logos or seals",
        },
        MFDS: {
            "status": "enabled" if mfds_serving_enabled() else "disabled",
            "gate": "BIO_SECTION_ENABLED + MFDS_ENABLED",
            "fetch_key": "present" if config.MFDS_API_KEY else "absent_in_this_process",
            "fetch_gate": "MFDS_API_KEY or FSC_API_KEY (ingest only)",
        },
        CHAIN_GAS: {
            "status": chain_gas_status(),
            "gate": "CRYPTO_SECTION_ENABLED + CHAIN_GAS_ENABLED + CHAIN_RPC_*_URL",
            "chains": chain_gas_configured_chains(),
        },
    }
    for provider_id in _MACRO_LANES:
        report[f"macro:{provider_id}"] = {
            "status": "enabled" if macro_lane_enabled(provider_id) else "disabled",
            "gate": _MACRO_LANE_GATES.get(provider_id, f"{provider_id.upper()}_ENABLED"),
        }
    return report
