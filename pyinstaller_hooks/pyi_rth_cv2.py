"""Runtime hook: force cv2 to insert its binary path at sys.path[0].

PyInstaller's macOS .app bundle places cv2's __init__.py at
Contents/Resources/cv2/ and adds Contents/Frameworks (which contains a
symlinked cv2/ pointing to Resources/cv2) to sys.path[0].  cv2's bootstrap
computes LOADER_DIR via realpath of __file__ — that resolves through the
symlink to Resources/cv2, so its check `sys.path[0] == dirname(LOADER_DIR)`
fails, the workaround is skipped, and the .so is inserted at position 1.
Python then finds cv2/__init__.py before cv2.abi3.so on the second import,
which retriggers bootstrap and raises a recursion error.

Setting this flag forces the workaround unconditionally.
"""
import sys

sys.OpenCV_REPLACE_SYS_PATH_0 = True
