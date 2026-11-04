"""Exception types shared across TESSERA."""


class TesseraError(Exception):
    """Base class for all TESSERA errors."""


class PolicyError(TesseraError):
    """A policy file is missing, malformed or violates a safety invariant."""


class RestrictedDataUnavailable(TesseraError):
    """Restricted (DFSA) data was requested outside ``RESEARCH_INTERNAL`` mode."""


class IngestError(TesseraError):
    """A manually obtained file could not be ingested."""


class SyntheticInputRejected(TesseraError, ValueError):
    """An offer was not clearly labelled as synthetic."""


class RestrictedValueLeak(TesseraError):
    """A restricted value was about to leave the masked world. Nothing was sent or written."""


class GoldLabelLeak(TesseraError):
    """A ``gold_*`` field was about to reach a system under test. Nothing was sent."""


class RequestBudgetExceeded(TesseraError):
    """The case used up its model-request budget (reason U7)."""
