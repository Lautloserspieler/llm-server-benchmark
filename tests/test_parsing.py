from llmbench.llama_bench import _extract_json, flatten_bench_rows


def test_extract_json_clean():
    data = _extract_json('[{"n_prompt":512,"n_gen":0,"n_depth":0,"avg_ts":100.5,"stddev_ts":1.2}]')
    assert data[0]["avg_ts"] == 100.5


def test_extract_json_with_noise():
    data = _extract_json('notice\\n[{"n_prompt":0,"n_gen":128,"n_depth":0,"avg_ts":55.0}]\\n')
    assert data[0]["n_gen"] == 128


def test_flat_derives_name():
    result = {"status": "ok", "rows": [{"n_prompt": 0, "n_gen": 512, "n_depth": 8192, "avg_ts": 42.0}]}
    rows = flatten_bench_rows(result)
    assert rows[0]["test"] == "tg512@d8192"
