import argparse
from pathlib import Path

import matplotlib

if __name__ != "__main__":
    matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def read_spc_file(file_path: Path) -> tuple[np.ndarray, np.ndarray]:
    """
    Read spectrum data from a .spc file.

    Priority:
    1) Use `spc` package for binary SPC files.
    2) Use `spc_spectra` package for binary SPC files.
    3) Fallback to text parsing (two-column numeric data).
    """
    # Try binary SPC reader first.
    try:
        import spc  # type: ignore

        spectrum = spc.File(str(file_path))
        x = np.array(spectrum.x, dtype=float)

        # Different SPC files may store y differently.
        if hasattr(spectrum, "sub") and spectrum.sub:
            y = np.array(spectrum.sub[0].y, dtype=float)
        elif hasattr(spectrum, "y"):
            y = np.array(spectrum.y, dtype=float)
        else:
            raise ValueError("SPC 文件中未找到可用的强度数据。")

        return x, y
    except ModuleNotFoundError:
        # If spc package is not installed, try text fallback.
        pass
    except Exception:
        # Binary parsing failed, try text fallback.
        pass

    # Try alternative binary reader.
    try:
        from spc_spectra import File  # type: ignore

        spectrum = File(str(file_path))
        x = np.array(spectrum.x, dtype=float)
        if hasattr(spectrum, "sub") and spectrum.sub:
            y = np.array(spectrum.sub[0].y, dtype=float)
        elif hasattr(spectrum, "y"):
            y = np.array(spectrum.y, dtype=float)
        else:
            raise ValueError("SPC 文件中未找到可用的强度数据。")
        return x, y
    except ModuleNotFoundError:
        pass
    except Exception:
        pass

    # Fallback: treat .spc as text data file (two numeric columns).
    try:
        data = np.loadtxt(file_path, comments=["#", ";", "//"])
    except Exception as exc:
        raise RuntimeError(
            "无法读取该 .spc 文件。当前环境若为 Python 3.14，旧版 SPC 读取库可能无法安装。"
            "建议创建 Python 3.11 虚拟环境后安装: pip install numpy matplotlib spc_spectra；"
            "或确认文件是纯文本两列数据格式。"
        ) from exc

    if data.ndim != 2 or data.shape[1] < 2:
        raise ValueError("文本格式 .spc 文件应至少包含两列数值数据（x y）。")

    x = data[:, 0]
    y = data[:, 1]
    return x, y


def plot_spectrum(
    x: np.ndarray,
    y: np.ndarray,
    title: str,
    xlabel: str,
    ylabel: str,
    save_path: Path | None = None,
) -> None:
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(x, y, linewidth=1.2)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(alpha=0.3)
    fig.tight_layout()

    if save_path is not None:
        fig.savefig(save_path, dpi=200)
        print(f"图像已保存: {save_path}")
    else:
        plt.show()
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="读取 .spc 文件并绘制光谱图。")
    parser.add_argument("spc_file", type=Path, help=".spc 文件路径")
    parser.add_argument("--title", default="SPC Spectrum", help="图标题")
    parser.add_argument("--xlabel", default="波长（nm）", help="X 轴标签")
    parser.add_argument("--ylabel", default="强度", help="Y 轴标签")
    parser.add_argument(
        "--save",
        type=Path,
        default=None,
        help="保存图片路径（如 out.png）。不传则直接弹窗显示。",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    spc_path = args.spc_file

    if not spc_path.exists():
        raise FileNotFoundError(f"文件不存在: {spc_path}")

    x, y = read_spc_file(spc_path)
    plot_spectrum(
        x=x,
        y=y,
        title=args.title,
        xlabel=args.xlabel,
        ylabel=args.ylabel,
        save_path=args.save,
    )


if __name__ == "__main__":
    main()
