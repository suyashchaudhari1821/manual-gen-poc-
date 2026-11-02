import py7zr

with py7zr.SevenZipFile("Machining Fixture (1).7z", mode="r") as z:
    print(z.getnames())