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
