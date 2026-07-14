def converter_numpy(obj):
    if isinstance(obj, dict):
        return {k: converter_numpy(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [converter_numpy(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(converter_numpy(v) for v in obj)
    if hasattr(obj, "tolist"):
        return obj.tolist()
    if hasattr(obj, "item"):
        return obj.item()
    return obj
