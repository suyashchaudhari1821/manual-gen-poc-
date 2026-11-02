try:
    from langsmith import traceable

except Exception:

    def traceable(*args, **kwargs):
        def wrapper(fn):
            return fn

        return wrapper
