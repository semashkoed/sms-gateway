from pathlib import Path

from app.router import Route, Router


def test_longest_prefix_wins():
    router = Router(
        [Route("+7", ["a"]), Route("+7913", ["b", "c"]), Route("+79131", ["d"])],
        default=["z"],
    )
    assert router.resolve("+79131234567") == ["d"]
    assert router.resolve("+79139999999") == ["b", "c"]
    assert router.resolve("+79001234567") == ["a"]
    assert router.resolve("+375291234567") == ["z"]


def test_config_file_is_valid():
    path = Path(__file__).resolve().parent.parent / "config" / "routes.json"
    router = Router.from_file(path)
    assert router.resolve("+79021234567")[0] == "tele2"
