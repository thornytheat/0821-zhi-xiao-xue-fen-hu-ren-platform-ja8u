EXPECTED = {'0001': (3, 10, 'READY'),
 '0002': (2, 3, 'READY'),
 '0003': (0, None, 'UNKNOWN_COURSE'),
 '0004': (2, 4, 'CREDIT_SHORTFALL')}
EVIDENCE = {'0001': {'matched': {'1': 2, '2': 1}, 'unmet': []},
 '0004': {'matched': {'1': 1}, 'unmet': [2]}}
