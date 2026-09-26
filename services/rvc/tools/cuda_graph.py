def run_cuda_graph(model, name, func, *args):
    return func(*args)

def cuda_graph_enabled(*args, **kwargs):
    return False

def clear_cuda_graph_cache(*args, **kwargs):
    pass
