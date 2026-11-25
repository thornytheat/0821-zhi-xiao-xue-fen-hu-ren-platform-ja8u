from app.business import decision


def policy(result):
    return decision(result,'CREDIT_SHORTFALL' if result['value'] < result['expected'] else None,lower_bound=True)
