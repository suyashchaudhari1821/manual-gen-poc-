from stl import mesh
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import numpy as np
from matplotlib import cm
# =====================================
# STL FILE
# =====================================

STL_FILE = r"C:\Users\pgavhane\OneDrive - Expleo France\Documents\PROJECT\E5312070200000 1.stl"

# =====================================
# LOAD STL
# =====================================

stl_mesh = mesh.Mesh.from_file(STL_FILE)

print("Triangles:", len(stl_mesh.vectors))

# =====================================
# CREATE FIGURE
# =====================================

fig = plt.figure(figsize=(10, 8))
ax = fig.add_subplot(111, projection="3d")

# =====================================
# RENDER MESH
# =====================================
triangles = stl_mesh.vectors
# Average Z value of each triangle
z_mean = triangles[:, :, 2].mean(axis=1)
# Normalize
norm = plt.Normalize(
    z_mean.min(),
    z_mean.max()
)
colors = cm.viridis(norm(z_mean))
collection = Poly3DCollection(
    triangles,
    facecolors=colors,
    edgecolors="none"
)

ax.add_collection3d(collection)

# Remove mesh lines
points = stl_mesh.points.reshape(-1, 3)


# =====================================
# AUTO SCALE
# =====================================

points = stl_mesh.points.reshape(-1, 3)

x = points[:, 0]
y = points[:, 1]
z = points[:, 2]

ax.set_xlim(x.min(), x.max())
ax.set_ylim(y.min(), y.max())
ax.set_zlim(z.min(), z.max())
ax.set_box_aspect([
    x.max() - x.min(),
    y.max() - y.min(),
    z.max() - z.min()
])

ax.set_axis_off()

plt.tight_layout()

# =====================================
# SAVE PNG
# =====================================

OUTPUT_FILE = "render.png"

plt.savefig(
    OUTPUT_FILE,
    dpi=300,
    bbox_inches="tight"
)

plt.close()

print(f"Saved: {OUTPUT_FILE}")