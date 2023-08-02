class HistoryFetchFailedException(Exception):
    def __init__(self, message="Failed to fetch history data."):
        self.message = message
        super().__init__(self.message)

