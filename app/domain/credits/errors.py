class CreditError(Exception):
    pass


class InsufficientCreditsError(CreditError):
    def __init__(self, available: int, required: int) -> None:
        super().__init__(f"available {available}, required {required}")
        self.available = available
        self.required = required


class HoldNotActiveError(CreditError):
    def __init__(self, generation_id: int) -> None:
        super().__init__(f"no active hold for generation {generation_id}")
        self.generation_id = generation_id


class TrialAlreadyUsedError(CreditError):
    def __init__(self, user_id: int) -> None:
        super().__init__(f"user {user_id} already bought the trial pack")
        self.user_id = user_id
