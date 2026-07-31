import os
import tempfile
import unittest
from pathlib import Path

import chmtool


class ChmToolTests(unittest.TestCase):
    def test_discovers_html_case_insensitively(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "guide").mkdir()
            (root / "guide" / "B.HTML").write_text("B", encoding="utf-8")
            (root / "a.htm").write_text("A", encoding="utf-8")
            (root / "ignore.txt").write_text("no", encoding="utf-8")

            self.assertEqual(
                [path.as_posix() for path in chmtool.discover_html(root)],
                ["a.htm", "guide/B.HTML"],
            )

    def test_finds_default_topic_from_project_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs").mkdir()
            (root / "docs" / "start.htm").write_text("start", encoding="utf-8")
            (root / "other.html").write_text("other", encoding="utf-8")
            (root / "manual.hhp").write_bytes("[OPTIONS]\nDefault topic=docs\\start.htm\n".encode("gb18030"))
            pages = chmtool.discover_html(root)

            self.assertEqual(chmtool.find_default_topic(root, pages), Path("docs/start.htm"))

    def test_create_index_preserves_existing_index(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.html").write_text("original", encoding="utf-8")
            (root / "页面 & one.htm").write_text("page", encoding="utf-8")

            generated = chmtool.create_index(root)
            content = (root / generated).read_text(encoding="utf-8")

            self.assertEqual(generated, Path("chmtool-index.html"))
            self.assertEqual((root / "index.html").read_text(encoding="utf-8"), "original")
            self.assertIn("%E9%A1%B5%E9%9D%A2%20%26%20one.htm", content)
            self.assertIn("页面 &amp; one.htm", content)

    def test_create_index_uses_original_hhc_labels_and_hierarchy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "front.html").write_text("<title>前言页面</title>", encoding="utf-8")
            (root / "upgrade.html").write_text("<title>升级页面</title>", encoding="utf-8")
            (root / "path.html").write_text("<title>路径页面</title>", encoding="utf-8")
            (root / "orphan.html").write_text("<title>补充说明</title>", encoding="utf-8")
            contents = """<html><body><ul>
<li><object type="text/sitemap"><param name="Name" value="前言"><param name="Local" value="front.html"></object></li>
<li><object type="text/sitemap"><param name="Name" value="升级前必读"><param name="Local" value="upgrade.html"></object><ul>
<li><object type="text/sitemap"><param name="Name" value="升级路径"><param name="Local" value="path.html"></object></li>
</ul></li>
</ul></body></html>"""
            (root / "manual.hhc").write_bytes(contents.encode("gb18030"))

            generated = chmtool.create_index(root)
            content = (root / generated).read_text(encoding="utf-8")

            self.assertIn('src="front.html"', content)
            self.assertIn('>前言</a>', content)
            self.assertIn('>升级前必读</a>\n          <ul>', content)
            self.assertIn('>升级路径</a>', content)
            self.assertIn("未在 CHM 目录中的页面", content)
            self.assertIn('>补充说明</a>', content)

    def test_hhp_selects_referenced_contents_file_case_insensitively(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "nav").mkdir()
            (root / "first.hhc").write_text("<ul></ul>", encoding="utf-8")
            selected = root / "nav" / "Contents.HHC"
            selected.write_text("<ul></ul>", encoding="utf-8")
            (root / "manual.HHP").write_text(
                "[OPTIONS]\nContents file=nav\\contents.hhc\n",
                encoding="utf-8",
            )

            self.assertEqual(chmtool.find_contents_file(root), selected)

    def test_create_index_includes_resizable_sidebar(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "page.html").write_text("<title>页面</title>", encoding="utf-8")

            generated = chmtool.create_index(root)
            content = (root / generated).read_text(encoding="utf-8")

            self.assertIn('id="splitter" role="separator"', content)
            self.assertIn('aria-controls="viewer"', content)
            self.assertIn('id="viewer" name="viewer"', content)
            self.assertIn("splitter.addEventListener('pointermove'", content)
            self.assertIn("splitter.addEventListener('keydown'", content)
            self.assertIn("localStorage.setItem(SIDEBAR_STORAGE_KEY", content)
            self.assertIn("#splitter { display: none; }", content)
            self.assertIn("nav a { display: block;", content)
            self.assertIn("color: #374151;", content)
            self.assertIn("nav a:focus { color: #0369a1;", content)
            self.assertIn("nav a.is-active { color: #075985;", content)
            self.assertIn("link.classList.toggle('is-active', isActive)", content)

    def test_rejects_index_path_outside_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "page.html").write_text("page", encoding="utf-8")
            with self.assertRaises(chmtool.ChmToolError):
                chmtool.create_index(root, "../index.html")

    def test_rejects_index_name_in_subdirectory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "page.html").write_text("page", encoding="utf-8")
            with self.assertRaises(chmtool.ChmToolError):
                chmtool.create_index(root, "sub/index.html")

    def test_validate_source_checks_chm_signature(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "invalid.chm"
            source.write_bytes(b"not a chm")
            with self.assertRaises(chmtool.ChmToolError):
                chmtool.validate_source(source)

    @unittest.skipIf(os.name == "nt", "测试用的模拟解包器是 POSIX shell 脚本")
    def test_extract_chm_end_to_end_with_fake_backend(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "manual.chm"
            source.write_bytes(b"ITSF" + b"fake test data")
            output = root / "manual_html"
            extractor = root / "extract_chmLib"
            extractor.write_text(
                "#!/bin/sh\n"
                "mkdir -p \"$2/docs\"\n"
                "printf '<h1>Start</h1>' > \"$2/docs/start.html\"\n"
                "printf '[OPTIONS]\\nDefault topic=docs/start.html\\n' > \"$2/manual.hhp\"\n",
                encoding="utf-8",
            )
            extractor.chmod(0o755)

            backend, generated, page_count = chmtool.extract_chm(
                source, output, extractor=str(extractor)
            )

            self.assertEqual(backend.name, "extract_chmLib")
            self.assertEqual(generated, Path("index.html"))
            self.assertEqual(page_count, 1)
            self.assertTrue((output / "docs" / "start.html").is_file())
            self.assertIn(
                'src="docs/start.html"',
                (output / "index.html").read_text(encoding="utf-8"),
            )

    @unittest.skipIf(os.name == "nt", "测试用的模拟解包器是 POSIX shell 脚本")
    def test_overwrite_replaces_file_at_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "manual.chm"
            source.write_bytes(b"ITSF" + b"fake test data")
            extractor = root / "extract_chmLib"
            extractor.write_text(
                "#!/bin/sh\n"
                "mkdir -p \"$2\"\n"
                "printf '<h1>Page</h1>' > \"$2/page.html\"\n",
                encoding="utf-8",
            )
            extractor.chmod(0o755)
            output = root / "manual_html"
            output.write_text("旧文件", encoding="utf-8")

            with self.assertRaisesRegex(chmtool.ChmToolError, "不是目录"):
                chmtool.extract_chm(source, output, extractor=str(extractor))
            self.assertEqual(output.read_text(encoding="utf-8"), "旧文件")

            _, generated, page_count = chmtool.extract_chm(
                source, output, overwrite=True, extractor=str(extractor)
            )

            self.assertTrue(output.is_dir())
            self.assertEqual(generated, Path("index.html"))
            self.assertEqual(page_count, 1)
            self.assertTrue((output / "page.html").is_file())


if __name__ == "__main__":
    unittest.main()
