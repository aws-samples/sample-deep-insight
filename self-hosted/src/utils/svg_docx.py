"""SVG embedding for DOCX charts (Office 2016+ native vector rendering).

When matplotlib charts are saved as both PNG and SVG, this module upgrades a
finished DOCX in-place so each embedded PNG also carries the SVG as a vector
extension (asvg:svgBlip). Word 2016+ / Microsoft 365 / LibreOffice 6.0+ render
the SVG natively; older viewers transparently fall back to the PNG.

Usage (in reporter agent):

    doc.save(report_path)
    from src.utils.svg_docx import finalize_svg_embeddings
    upgraded = finalize_svg_embeddings(report_path, artifacts_dir='./artifacts')

The function is idempotent: re-running on an already-upgraded DOCX is a no-op.
PNGs without a matching SVG sibling pass through unchanged.

Matching strategy: each embedded PNG is hashed (SHA-1) and looked up against the
SHA-1 of every PNG in artifacts_dir whose .svg sibling exists. This works
regardless of how python-docx renamed images during insertion.
"""
from __future__ import annotations

import hashlib
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Union

from lxml import etree


_NS = {
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'asvg': 'http://schemas.microsoft.com/office/drawing/2016/SVG/main',
    'rels': 'http://schemas.openxmlformats.org/package/2006/relationships',
    'ct': 'http://schemas.openxmlformats.org/package/2006/content-types',
}

_SVG_EXT_URI = '{96DAC541-7B7A-43D3-8B79-37D633B846F1}'  # Microsoft standard SVG extension URI
_IMAGE_REL_TYPE = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/image'


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def finalize_svg_embeddings(docx_path: Union[str, Path], artifacts_dir: Union[str, Path]) -> int:
    """Upgrade embedded PNG charts to dual PNG+SVG embedding.

    Args:
        docx_path: DOCX file to upgrade in place.
        artifacts_dir: Directory containing chart sources. For each `<name>.png`
            with a sibling `<name>.svg`, the SVG is embedded as a vector
            extension on every matching PNG inside the DOCX.

    Returns:
        Number of blip elements upgraded.
    """
    docx_path = Path(docx_path)
    artifacts_dir = Path(artifacts_dir)

    if not docx_path.exists():
        raise FileNotFoundError(f"DOCX not found: {docx_path}")
    if not artifacts_dir.exists():
        return 0

    png_hash_to_svg: dict[str, Path] = {}
    for png_file in artifacts_dir.rglob('*.png'):
        svg_file = png_file.with_suffix('.svg')
        if svg_file.exists():
            png_hash_to_svg[_sha256_file(png_file)] = svg_file

    if not png_hash_to_svg:
        return 0

    tmp_dir = Path(tempfile.mkdtemp(prefix='docx_svg_'))
    try:
        with zipfile.ZipFile(docx_path, 'r') as zf:
            zf.extractall(tmp_dir)

        media_dir = tmp_dir / 'word' / 'media'
        if not media_dir.exists():
            return 0

        media_to_svg: dict[str, Path] = {}
        for png_in_docx in media_dir.glob('*.png'):
            docx_hash = _sha256_file(png_in_docx)
            if docx_hash in png_hash_to_svg:
                media_to_svg[png_in_docx.name] = png_hash_to_svg[docx_hash]

        if not media_to_svg:
            return 0

        rels_path = tmp_dir / 'word' / '_rels' / 'document.xml.rels'
        rels_xml = etree.parse(str(rels_path))
        rels_root = rels_xml.getroot()

        target_to_rid: dict[str, str] = {}
        max_rid = 0
        for r in rels_root:
            rid = r.get('Id', '')
            if rid.startswith('rId') and rid[3:].isdigit():
                max_rid = max(max_rid, int(rid[3:]))
            target = r.get('Target', '')
            if target.startswith('media/'):
                target_to_rid[Path(target).name] = rid

        png_rid_to_svg_rid: dict[str, str] = {}
        for media_name, svg_src in media_to_svg.items():
            svg_target_name = Path(media_name).stem + '.svg'
            shutil.copy(svg_src, media_dir / svg_target_name)

            max_rid += 1
            new_rid = f'rId{max_rid}'
            rel_elem = etree.SubElement(rels_root, f"{{{_NS['rels']}}}Relationship")
            rel_elem.set('Id', new_rid)
            rel_elem.set('Type', _IMAGE_REL_TYPE)
            rel_elem.set('Target', f'media/{svg_target_name}')

            png_rid = target_to_rid.get(media_name)
            if png_rid:
                png_rid_to_svg_rid[png_rid] = new_rid

        rels_xml.write(str(rels_path), xml_declaration=True, encoding='UTF-8', standalone=True)

        ct_path = tmp_dir / '[Content_Types].xml'
        ct_xml = etree.parse(str(ct_path))
        ct_root = ct_xml.getroot()
        if not any(d.get('Extension') == 'svg' for d in ct_root.findall(f"{{{_NS['ct']}}}Default")):
            new_default = etree.SubElement(ct_root, f"{{{_NS['ct']}}}Default")
            new_default.set('Extension', 'svg')
            new_default.set('ContentType', 'image/svg+xml')
            ct_xml.write(str(ct_path), xml_declaration=True, encoding='UTF-8', standalone=True)

        doc_path = tmp_dir / 'word' / 'document.xml'
        doc_xml = etree.parse(str(doc_path))
        upgraded = 0
        for blip in doc_xml.findall(f".//{{{_NS['a']}}}blip"):
            png_rid = blip.get(f"{{{_NS['r']}}}embed")
            svg_rid = png_rid_to_svg_rid.get(png_rid)
            if not svg_rid:
                continue
            if blip.find(
                f"{{{_NS['a']}}}extLst/{{{_NS['a']}}}ext/{{{_NS['asvg']}}}svgBlip"
            ) is not None:
                continue
            ext_lst = blip.find(f"{{{_NS['a']}}}extLst")
            if ext_lst is None:
                ext_lst = etree.SubElement(blip, f"{{{_NS['a']}}}extLst")
            ext = etree.SubElement(ext_lst, f"{{{_NS['a']}}}ext")
            ext.set('uri', _SVG_EXT_URI)
            svg_blip = etree.SubElement(ext, f"{{{_NS['asvg']}}}svgBlip")
            svg_blip.set(f"{{{_NS['r']}}}embed", svg_rid)
            upgraded += 1

        doc_xml.write(str(doc_path), xml_declaration=True, encoding='UTF-8', standalone=True)

        out_tmp = docx_path.with_suffix(docx_path.suffix + '.tmp')
        with zipfile.ZipFile(out_tmp, 'w', zipfile.ZIP_DEFLATED) as zf:
            for fp in tmp_dir.rglob('*'):
                if fp.is_file():
                    zf.write(fp, fp.relative_to(tmp_dir))
        out_tmp.replace(docx_path)
        return upgraded
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
