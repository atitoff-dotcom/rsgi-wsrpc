from typing import Callable, List, Tuple

# Реестр HTTP-роутов. Формат: [(path, methods, handler)]
HTTP_ROUTES: List[Tuple[str, List[str], Callable]] = []

def http_route(path: str, methods: List[str] = None) -> Callable:
    """
    Декоратор для регистрации HTTP-обработчиков (роутов) в приложении.
    """
    if methods is None:
        methods = ["GET"]
    else:
        methods = [m.upper() for m in methods]

    def decorator(func: Callable) -> Callable:
        HTTP_ROUTES.append((path, methods, func))
        return func
    return decorator
