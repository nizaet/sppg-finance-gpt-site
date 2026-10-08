"""Defaults for a new service date; never copy movements or bank balances."""
from copy import deepcopy

def carry_opening(daily, closing, source_date):
    result=deepcopy(daily)
    balance=result.setdefault('balance', {})
    for component, field in (('raw','openingRaw'),('operational','openingOperational'),('incentive','openingIncentive')):
        if balance.get(field) in (None, ''):
            balance[field]=closing[component]
    result['_openingBalanceSourceDate']=str(source_date)
    return result

