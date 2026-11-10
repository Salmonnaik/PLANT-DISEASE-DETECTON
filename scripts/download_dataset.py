"""
download_dataset.py
===================
Helper for obtaining a plant disease dataset so the model can be trained.

The repository ships **no dataset** - PlantVillage is several gigabytes and is
distributed under terms that require you to accept them yourself. This script
automates the download when you have credentials, and prints exact manual
instructions when you do not.

    python scripts/download_dataset.py --check          # what is present now
    python scripts/download_dataset.py                  # try an automatic download
    python scripts/download_dataset.py --list-classes   # inspect what was obtained

After a successful download:

    python ml/train.py --validate-only          # confirm the layout
    python ml/train.py --max-images-per-class 300   # quick trial run
    python ml/train.py                          # full training
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = ROOT / "ml" / "dataset"

# Kaggle dataset slugs that provide PlantVillage in the expected
# one-directory-per-class layout.
KAGGLE_CANDIDATES = (
    "abdallahalidev/plantvillage-dataset",
    "emmarex/plantdisease",
)

GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
GREY = "\033[90m"
BOLD = "\033[1m"
RESET = "\033[0m"

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def summarise(dataset_dir: Path = DATASET_DIR) -> dict:
    """Count class folders and images currently present."""
    if not dataset_dir.is_dir():
        return {"exists": False, "classes": 0, "images": 0, "per_class": {}}

    per_class = {}
    for entry in sorted(dataset_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        count = sum(
            1 for item in entry.rglob("*")
            if item.is_file() and item.suffix.lower() in IMAGE_SUFFIXES
        )
        per_class[entry.name] = count

    return {
        "exists": True,
        "classes": len(per_class),
        "images": sum(per_class.values()),
        "per_class": per_class,
    }


def print_status(dataset_dir: Path = DATASET_DIR) -> bool:
    """Print the current dataset state. Returns True if it looks trainable."""
    report = summarise(dataset_dir)

    print(f"{BOLD}Dataset status{RESET}")
    print(f"{GREY}Location: {dataset_dir}{RESET}")

    if not report["exists"] or report["classes"] == 0:
        print(f"  {RED}No dataset present.{RESET} 0 class folders found.")
        print(f"  {YELLOW}The model therefore cannot be trained yet.{RESET}")
        return False

    print(f"  {GREEN}{report['classes']} classes, {report['images']} images{RESET}")
    width = max(len(name) for name in report["per_class"])
    for name, count in report["per_class"].items():
        flag = f"  {YELLOW}(low){RESET}" if count < 50 else ""
        print(f"    {name.ljust(width)}  {count}{flag}")

    trainable = report["classes"] >= 2 and report["images"] >= 40
    if not trainable:
        print(f"  {YELLOW}Not enough data to train: need at least 2 classes.{RESET}")
    return trainable


def have_command(name: str) -> bool:
    return shutil.which(name) is not None


def try_kagglehub() -> Optional[Path]:
    """Download with the kagglehub library, if it is installed and configured."""
    try:
        import kagglehub  # noqa: PLC0415
    except ImportError:
        return None

    for slug in KAGGLE_CANDIDATES:
        print(f"  Trying kagglehub: {slug} ...")
        try:
            path = Path(kagglehub.dataset_download(slug))
            print(f"  {GREEN}Downloaded to {path}{RESET}")
            return path
        except Exception as exc:  # noqa: BLE001
            print(f"  {YELLOW}Failed: {exc}{RESET}")
    return None


def try_kaggle_cli() -> Optional[Path]:
    """Download with the kaggle CLI, if it is installed and authenticated."""
    if not have_command("kaggle"):
        return None

    target = ROOT / "ml" / ".dataset_download"
    target.mkdir(parents=True, exist_ok=True)

    for slug in KAGGLE_CANDIDATES:
        print(f"  Trying kaggle CLI: {slug} ...")
        result = subprocess.run(
            ["kaggle", "datasets", "download", "-d", slug, "-p", str(target), "--unzip"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print(f"  {GREEN}Downloaded to {target}{RESET}")
            return target
        print(f"  {YELLOW}Failed: {result.stderr.strip()[:200]}{RESET}")
    return None


def find_class_root(root: Path) -> Optional[Path]:
    """
    Locate the directory that directly contains the class folders.

    Downloads nest the useful directory at varying depths (often inside
    ``plantvillage dataset/color/``), so the tree is searched for the first
    directory whose children are themselves image-bearing folders.
    """
    best: Optional[Path] = None
    best_count = 0

    for candidate in [root, *[p for p in root.rglob("*") if p.is_dir()]]:
        subdirs = [p for p in candidate.iterdir() if p.is_dir() and not p.name.startswith(".")]
        if len(subdirs) < 2:
            continue
        with_images = 0
        for subdir in subdirs:
            has_image = any(
                item.suffix.lower() in IMAGE_SUFFIXES
                for item in subdir.iterdir()
                if item.is_file()
            )
            if has_image:
                with_images += 1
        # Prefer the directory with the most image-bearing children.
        if with_images >= 2 and with_images > best_count:
            best, best_count = candidate, with_images

    return best


def link_into_dataset(source_root: Path, dataset_dir: Path = DATASET_DIR) -> int:
    """
    Copy class folders into ml/dataset/.

    Hard-links where the filesystem allows it, so a multi-gigabyte dataset is
    not duplicated on disk.
    """
    class_root = find_class_root(source_root)
    if class_root is None:
        print(f"  {RED}Could not find class folders inside {source_root}{RESET}")
        return 0

    print(f"  Class folders found in: {class_root}")
    dataset_dir.mkdir(parents=True, exist_ok=True)
    linked = 0

    for class_dir in sorted(p for p in class_root.iterdir() if p.is_dir()):
        target_dir = dataset_dir / class_dir.name
        target_dir.mkdir(exist_ok=True)
        for image in class_dir.rglob("*"):
            if not image.is_file() or image.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            target = target_dir / image.name
            if target.exists():
                continue
            try:
                target.hardlink_to(image)
            except (OSError, NotImplementedError):
                shutil.copy2(image, target)
            linked += 1

    return linked


def print_manual_instructions() -> None:
    print()
    print(f"{BOLD}Manual download{RESET}")
    print("  No automatic download was possible. Either option works:")
    print()
    print(f"  {BOLD}Option A - Kaggle (recommended){RESET}")
    print("    1. Create a free account at https://www.kaggle.com")
    print("    2. Account -> Settings -> API -> 'Create New Token'")
    print(f"    3. Save kaggle.json to {Path.home() / '.kaggle' / 'kaggle.json'}")
    print("    4. pip install kagglehub")
    print("    5. Re-run this script")
    print()
    print(f"  {BOLD}Option B - download the archive by hand{RESET}")
    print("    1. https://www.kaggle.com/datasets/abdallahalidev/plantvillage-dataset")
    print("       (or the original: https://github.com/spMohanty/PlantVillage-Dataset)")
    print("    2. Extract it")
    print(f"    3. Copy the class folders into {DATASET_DIR}")
    print("       so the layout is one directory per class:")
    print()
    print(f"{GREY}         ml/dataset/")
    print("           Tomato___Early_blight/      image (1).JPG ...")
    print("           Tomato___healthy/           image (1).JPG ...")
    print(f"           Potato___Late_blight/       image (1).JPG ...{RESET}")
    print()
    print("  Folder names become the class labels, so keep the")
    print("  Plant___Condition convention. Any number of classes is fine -")
    print("  the dashboard reads the list from the trained model.")
    print()
    print(f"  {BOLD}Then train:{RESET}")
    print("    python ml/train.py --validate-only")
    print("    python ml/train.py --max-images-per-class 300    # quick trial")
    print("    python ml/train.py                               # full run")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Report the current state and exit")
    parser.add_argument("--list-classes", action="store_true", help="List class folders and counts")
    parser.add_argument("--dataset-dir", type=Path, default=DATASET_DIR)
    args = parser.parse_args(argv)

    if args.check or args.list_classes:
        return 0 if print_status(args.dataset_dir) else 1

    print(f"{BOLD}PlantGuard AI - dataset acquisition{RESET}\n")
    if print_status(args.dataset_dir):
        print(f"\n{GREEN}A dataset is already present. Nothing to do.{RESET}")
        print("Train with:  python ml/train.py")
        return 0

    print(f"\n{BOLD}Attempting an automatic download{RESET}")
    source = try_kagglehub() or try_kaggle_cli()

    if source is None:
        print(f"\n  {YELLOW}No configured Kaggle credentials were found.{RESET}")
        print_manual_instructions()
        return 1

    print(f"\n{BOLD}Importing into {args.dataset_dir}{RESET}")
    count = link_into_dataset(source, args.dataset_dir)
    if count == 0:
        print(f"  {RED}No images were imported.{RESET}")
        print_manual_instructions()
        return 1

    print(f"  {GREEN}Imported {count} images{RESET}\n")
    print_status(args.dataset_dir)
    print(f"\n{GREEN}Ready to train:{RESET}")
    print("  python ml/train.py --max-images-per-class 300    # quick trial")
    print("  python ml/train.py                               # full run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
