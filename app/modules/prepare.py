from app.business import DomainIssue, by_kind, prepared, single


def prepare(rows):
    external = by_kind(rows,'external')
    required = by_kind(rows,'required')
    sources = {r['external_course']:r['credits'] for r in external}
    targets = {r['local_course']:r['credits'] for r in required}
    if not sources or not targets or len(sources) != len(external) or len(targets) != len(required):
        raise DomainIssue('COURSE_REGISTER_CONFLICT')
    if len(targets) > 12 or len(sources) > 120:
        raise DomainIssue('COURSE_LIMIT')
    edges = {}
    for row in by_kind(rows,'equivalence'):
        source, target, credits, priority = (row[k] for k in ('external_course','local_course','credits','priority'))
        if source not in sources or target not in targets:
            raise DomainIssue('UNKNOWN_COURSE')
        maximum = min(sources[source],targets[target])
        if (source,target) in edges or not 0 < credits <= maximum:
            raise DomainIssue('INVALID_EQUIVALENCE')
        edges[source,target] = (credits,priority)
    floor = single(rows,'authorization')['credits']
    return prepared(len(edges),{'external':len(sources),'local':len(targets),'required_credits':floor},(sources,targets,edges,floor))
