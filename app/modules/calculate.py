from app.business import measured


def compute(data):
    sources, targets, edges, floor = data
    bits = {key:1 << index for index,key in enumerate(sorted(targets))}
    frontier = {0:(0,0,())}
    for source in sorted(sources):
        updated = dict(frontier)
        for (left,target),(credits,priority) in edges.items():
            if left != source:
                continue
            for mask,(total,rank,path) in frontier.items():
                if mask & bits[target]:
                    continue
                next_mask = mask | bits[target]
                proposal = (total+credits,rank+priority,(*path,(source,target)))
                current = updated.get(next_mask)
                if current is None or (-proposal[0],-proposal[1],proposal[2]) < (-current[0],-current[1],current[2]):
                    updated[next_mask] = proposal
        frontier = updated
    total, _, path = min(frontier.values(),key=lambda x:(-x[0],-x[1],x[2]))
    assigned = dict(path)
    return measured(total,floor,'学分',{'matched':{str(k):v for k,v in path},'unmet':sorted(targets.keys()-set(assigned.values()))})
