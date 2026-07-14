class DashboardError(Exception):
    """An error safe to show to the local user."""


class WorkbookValidationError(DashboardError):
    pass


class MarketDataError(DashboardError):
    pass
