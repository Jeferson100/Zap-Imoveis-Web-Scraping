def converter_numpy(obj):
    if isinstance(obj, dict):
        return {k: converter_numpy(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [converter_numpy(v) for v in obj]
    elif isinstance(obj, tuple):
        return tuple(converter_numpy(v) for v in obj)
    elif hasattr(obj, "tolist"):
        return obj.tolist()
    elif hasattr(obj, "item"):
        return obj.item()
    return obj
