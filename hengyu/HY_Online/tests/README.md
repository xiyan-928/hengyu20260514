# HY_Online 测试说明

## 依赖

在 `HY_Online` 目录安装（含可选测试依赖）：

```bash
pip install -r requirements.txt
```

测试额外需要：`pytest`、`httpx`（已写入 `requirements.txt`）。

## 运行方式

**必须在 `HY_Online` 目录下执行**，否则 Python 找不到 `auto_control_manager` 等包（不是缺少名为 `tests` 的第三方库）。

### 单元测试（unittest，不启动 HTTP）

```bash
conda run -n ftapi python -m unittest discover -s tests -p "test_auto_control_scripting.py" -v
```

### 端到端（pytest + TestClient，Mock 模式）

`tests/conftest.py` 会设置 `DEVICE_MODE=mock`，与 `start.py` 行为一致。

```bash
conda run -n ftapi pytest tests/test_e2e_mock.py -v
```

全部测试：

```bash
conda run -n ftapi pytest tests -v
```

### 与真实进程联调

若要对已运行的 `python start.py` 做 HTTP 手工验证，请另开终端访问 `http://127.0.0.1:8000/health` 等接口；本目录下的 E2E 使用内存 TestClient，**不需要**单独起服务。
