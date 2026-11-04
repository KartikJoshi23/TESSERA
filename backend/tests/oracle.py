"""A perfect reading of every smoke case, for the crew that works from a reading.

It answers one question: if every agent does its job, does the deterministic policy reach each smoke
case's gold result, for the gold reasons? Facts a model would read from the offer are listed by hand
in ``ORACLE``. Everything else comes from the tools, through the crew RULES-ONLY uses.
"""

from __future__ import annotations

from typing import Any

from tessera.baseline.rules_only import Reading as Facts
from tessera.baseline.rules_only import ToolCrew

ORACLE: dict[str, Facts] = {
    "S01": Facts(
        ((("DER.FX_CFD"), "spot FX and CFD trading"),),
        {"CMA": "primary"},
        firm="Falcon Ridge Securities L.L.C.",
    ),
    "S02": Facts(
        (("VA.EXCHANGE", "Trade bitcoin"),),
        {"VARA": "primary"},
        firm="Coral Ledger Exchange FZE",
        regulator=("VARA", "licensed by VARA"),
        reference="VL/26/01/001",
    ),
    "S03": Facts(
        (("SEC.ADVICE", "financial consultation"),),
        {"CMA": "primary"},
        firm="Oasis Bridge Financial Consultancy LLC",
        regulator=("SCA", "licensed by the SCA"),
    ),
    "S04": Facts(
        (("SEC.ADVICE", "advise you on financial products"),),
        {"DFSA": "primary"},
        firm="Lumen Crest Capital (DIFC) Limited",
        reference="F000000",
    ),
    "S05": Facts(
        (("FUND.MGMT", "manages portfolios"),),
        {"DFSA": "primary"},
        firm="Harbour Cedar Asset Management (DIFC) Limited",
        regulator=("DFSA", "regulated by the DFSA"),
    ),
    "S06": Facts(
        (("VA.CUSTODY", "custody for your crypto"),),
        {"VARA": "primary"},
        firm="Azure Dhow Digital FZE",
        regulator=("VARA", "licensed by VARA"),
    ),
    "S07": Facts(
        (("FUND.MGMT", "fund management"),),
        {"CMA": "primary"},
        firm="Desert Lantern Capital PJSC",
        regulator=("CMA", "CMA licensed"),
    ),
    "S08": Facts(
        (("SEC.BROKERAGE", "securities dealing"),),
        {"CMA": "primary"},
        firm="Falcon Ridge Securities",
    ),
    "S09": Facts(
        (("VA.EXCHANGE", "BTC trading"), ("VA.YIELD", "USDT staking")),
        {"DFSA": "primary", "VARA": "possible", "CMA": "possible"},
        firm="Lumen Crest Capital (DIFC) Limited",
        regulator=("DFSA", "regulated by the DFSA"),
        reference="F000000",
        not_covered={"VA.EXCHANGE": "SCOPE-DFSA-01", "VA.YIELD": "SCOPE-DFSA-01"},
        payment={"wallet_requested": True},
    ),
    "S10": Facts(
        (("DER.FX_CFD", "Trade CFDs and forex"),),
        {"CMA": "primary"},
        firm="Oasis Bridge Financial Consultancy LLC",
        regulator=("CMA", "CMA licensed"),
        not_covered={"DER.FX_CFD": "SCOPE-CMA-01"},
    ),
    "S11": Facts(
        (("VA.CUSTODY", "Store your crypto"),),
        {"VARA": "primary"},
        firm="Saffron Chain Custody FZCO",
        regulator=("VARA", "fully licensed VARA firm"),
        not_covered={"VA.CUSTODY": "SCOPE-VARA-02"},
    ),
    "S12": Facts(
        (("VA.EXCHANGE", "buy and sell USDT"),),
        {"VARA": "primary"},
        firm="Mirage Coin Hub",
    ),
    "S13": Facts(((("DER.FX_CFD"), "forex signals"),), {"CMA": "primary"}),
    "S14": Facts(
        (("FUND.MGMT", "private markets fund"),),
        {"DFSA": "primary"},
        firm="Zenith Harbor Partners",
        regulator=("Dubai Financial Services Authority", "Dubai Financial Services Authority"),
    ),
    "S15": Facts(
        (("DER.FX_CFD", "FX account"),),
        {"CMA": "primary"},
        firm="Falcon Ridge Securities L.L.C.",
    ),
    "S16": Facts(
        (("FUND.MGMT", "managed portfolios"),),
        {"DFSA": "primary"},
        firm="Cedar Harbour Wealth",
        regulator=("DFSA", "DFSA Firm Reference Number"),
        reference="F000001",
    ),
    "S17": Facts(
        (("DER.FX_CFD", "FX account"),),
        {"CMA": "primary"},
        firm="Falcon Ridge Securities L.L.C.",
        payment={"iban": "AE07 0331 2345 6789 0123 456", "beneficiary": "XYZ General Trading"},
    ),
    "S18": Facts(
        (("OTHER", "investment account"),),
        {"DFSA": "primary"},
        regulator=("DFSA", "FROM THE DFSA"),
    ),
    "S19": Facts(
        (("VA.EXCHANGE", "Our exchange"),),
        {"VARA": "primary"},
        firm="Northern Dune Digital",
        regulator=("VARA", "licensed by VARA"),
        reference="VL/26/01/001",
    ),
    "S20": Facts(
        (("VA.MGMT", "managed crypto portfolios"),),
        {"VARA": "possible", "CMA": "possible", "DFSA": "possible"},
        firm="Bluewave Horizon",
    ),
    "S21": Facts(
        (("LOAN.CREDIT", "personal loans"),),
        {"CBUAE": "primary"},
        firm="Amber Creek Finance PJSC",
    ),
    "S22": Facts(
        (("FUND.MGMT", "wealth management"),),
        {"FSRA": "primary"},
        firm="Falak Harbour Capital (ADGM) Ltd",
    ),
    "S23": Facts(
        (("DER.FX_CFD", "FX market notes"),),
        {"CMA": "primary"},
        firm="Falcon Ridge Securities L.L.C.",
    ),
    "S24": Facts(
        (("VA.EXCHANGE", "crypto account"),),
        {"VARA": "primary"},
        firm="Coral Ledger Exchange FZE",
    ),
    "S25": Facts(
        (("DER.FX_CFD", "gold CFDs"),),
        {"CMA": "primary"},
        firm="Meridian Dune Brokers LLC",
        regulator=("UAE Financial Trade Authority", "UAE Financial Trade Authority"),
    ),
}


def Oracle(setup: Any, facts: Facts) -> ToolCrew:
    return ToolCrew(setup.env, facts)


def run_oracle(setup: Any, key: str) -> ToolCrew:
    crew = Oracle(setup, ORACLE[key])
    crew.run()
    return crew
