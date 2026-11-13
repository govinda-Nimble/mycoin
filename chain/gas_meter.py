
from enum import Enum
from collections import defaultdict


class GasAction(Enum):
    BASE_TRANSACTION = "BASE_TRANSACTION"

    READ_ACCOUNT = "READ_ACCOUNT"
    READ_BALANCE = "READ_BALANCE"
    READ_NONCE = "READ_NONCE"

    UPDATE_BALANCE = "UPDATE_BALANCE"
    UPDATE_NONCE = "UPDATE_NONCE"

    CREATE_ACCOUNT = "CREATE_ACCOUNT"

    STAKE = "STAKE"
    UNSTAKE = "UNSTAKE"
    CLAIM_REWARD = "CLAIM_REWARD"


GAS_COSTS = {
    GasAction.BASE_TRANSACTION: 21000,

    GasAction.READ_ACCOUNT: 100,
    GasAction.READ_BALANCE: 100,
    GasAction.READ_NONCE: 100,

    GasAction.UPDATE_BALANCE: 200,
    GasAction.UPDATE_NONCE: 100,

    GasAction.CREATE_ACCOUNT: 25000,

    GasAction.STAKE: 20000,
    GasAction.UNSTAKE: 15000,
    GasAction.CLAIM_REWARD: 10000,
}



class OutOfGasError(Exception):
    pass


class GasMeter:
    """
    Calculate gas used to perform the transation. 
    """

    def __init__(self, gasLimit):

        if not isinstance(gasLimit, int) or gasLimit <= 0:
            raise ValueError("Invalid gas limit")

        self.gasLimit = gasLimit
        self.gasUsed = 0
        self.breakdown = defaultdict(int)

    def consume(self, action: GasAction):
        gasCost = GAS_COSTS[action]
        remainingGas = self.gasLimit - self.gasUsed

        if gasCost > remainingGas:
            self.gasUsed = self.gasLimit
            self.breakdown[action.value] += remainingGas
            raise OutOfGasError("Transaction ran out of gas")

        self.gasUsed += gasCost
        self.breakdown[action.value] += gasCost

    def getGasUsed(self):
        return self.gasUsed

    def getRemainingGas(self):
        return self.gasLimit - self.gasUsed

    def getBreakdown(self):
        return dict(self.breakdown)

    def calculateFee(self, gasPrice):
        if not isinstance(gasPrice, int) or gasPrice < 0:
            raise ValueError("Invalid gas price")

        return self.gasUsed * gasPrice




# gasMeter = GasMeter(gasLimit=30000)

# gasMeter.consume(GasAction.BASE_TRANSACTION)
# gasMeter.consume(GasAction.READ_BALANCE)
# gasMeter.consume(GasAction.UPDATE_BALANCE)

# print(gasMeter.getGasUsed())
# print(gasMeter.getRemainingGas())