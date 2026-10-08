"""(homemaker-py-y4p4) Price the owner's observation: a storey's circulation in two pieces is still
connected if each piece has its own stair. Counts, per corpus, how many
`level N not connected` fails would clear. Exact arithmetic, no score claimed."""
import copy, glob, sys, collections, os
import networkx as nx
os.environ["HOMEMAKER_ORTHOGONAL_DIVISION"] = "1"
from homemaker_layout import dom, geometry, graph as G, operators, fitness as F
geometry.ORTHOGONAL_DIVISION = True
orig = G.connected_circulation
def run(path, prog):
    conf, cost = F.load_config(prog); fit = F.Fitness(conf, cost)
    root = dom.load(path); dom.link(root); geometry.clear_cache()
    shafts = set(operators._shaft_paths(dom.levels(root)))
    calls = []
    def spy(g):
        ok = orig(g)                       # strips non-circulation in place
        calls.append([{(n.id or "") for n in c} for c in nx.connected_components(g)])
        return ok
    G.connected_circulation = spy
    try:
        s, fails = fit.score_with_fails(copy.deepcopy(root))
    finally:
        G.connected_circulation = orig
    nlv = len(dom.levels(root))
    assert len(calls) == nlv, (len(calls), nlv)
    uf = nx.Graph()
    for lv, comps in enumerate(calls):
        for k, c in enumerate(comps):
            uf.add_node((lv, k))
    for p in shafts:
        prev = None
        for lv, comps in enumerate(calls):
            here = next(((lv, k) for k, c in enumerate(comps) if p in c), None)
            if here and prev: uf.add_edge(prev, here)
            prev = here
    sets = list(nx.connected_components(uf))
    bad = [f for f in fails if f.startswith("level") and f.endswith("not connected")]
    cleared = 0
    for f in bad:
        lv = int(f.split()[1])
        if not calls[lv]: continue          # no circulation at all: stays
        home = {next(i for i, s_ in enumerate(sets) if (lv, k) in s_) for k in range(len(calls[lv]))}
        # ...and it must join the ground floor's circulation, not float free
        ground = {i for i, s_ in enumerate(sets) if any(l == 0 for l, _ in s_)}
        cleared += len(home) == 1 and home <= ground
    return len(fails), len(bad), cleared, len(shafts)
def corpus(name, files, prog_of):
    t = collections.Counter(); n = 0
    for f in files:
        nf, nb, nc, ns = run(f, prog_of(f)); n += 1
        t["fails"] += nf; t["not connected"] += nb; t["would clear"] += nc; t["designs with one"] += nb > 0; t["designs cleared of all"] += nb > 0 and nc == nb
    print(f"{name}: {n} designs, {dict(t)}", flush=True)
if __name__ == "__main__":
    print("hand2a:", run("examples/harbor-house/hand2a.dom", "examples/harbor-house"))
    # negative control: with no shafts offered, nothing may clear
    real = operators._shaft_paths; operators._shaft_paths = lambda l: []
    print("control, no stairs offered:", run("examples/harbor-house/hand2a.dom", "examples/harbor-house")); operators._shaft_paths = real
    for prog in ("programme-house", "health-centre", "harbor-house", "maple-court"):
        fs = sorted(glob.glob(f"examples/{prog}/coldstart-1a24b6a+orth-500000-s*.dom"))
        corpus(f"{prog} 1a24b6a+orth", fs, lambda f: os.path.dirname(f))
    fs = sorted(glob.glob("experiments/results/child20-ab/*child80*.dom"))
    corpus("programme-house child80 (64512f1+orth)", fs, lambda f: "examples/programme-house")
