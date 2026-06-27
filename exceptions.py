class MatchingEngineError(Exception):
    """Base exception for matching engine errors."""


class MarketResolvedError(MatchingEngineError):
    """Raised when submitting an order after the market has been resolved."""


class BookInvariantError(MatchingEngineError):
    """Raised when an internal order book invariant is violated."""
