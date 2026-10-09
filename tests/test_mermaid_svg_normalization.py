import os
import re
import shutil
import subprocess
import tempfile
import unittest
from collections import Counter
from pathlib import Path

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BUILD_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "build.yml"
NORMALIZER = REPOSITORY_ROOT / ".github" / "workflows" / "normalize-mermaid-svg.mjs"
UPDATE_SCRIPT = REPOSITORY_ROOT / "scripts" / "update-document-repos.mjs"

ID_ATTRIBUTE = re.compile(r'\sid="([^"]*)"')

# Twee diagrammen zoals mermaid ze genereert: identieke <defs>-id's, plus een
# intern layout-attribuut dat niet in SVG bestaat.
FIXTURE = """<!DOCTYPE html>
<html lang="nl"><head><meta charset="utf-8"><title>Test</title></head><body>
<pre><svg id="diagram-1" xmlns="http://www.w3.org/2000/svg" role="img"
 aria-labelledby="chart-title-diagram-1 chart-desc-diagram-1"><title
 id="chart-title-diagram-1">Een</title><desc id="chart-desc-diagram-1"></desc><style>
#diagram-1 :root{--mermaid-font-family:Arial;}#diagram-1 #arrowhead path{fill:#333;}</style><defs><marker id="arrowhead"><path
 d="M 0 0 L 10 5"></path></marker></defs><g class="node" label-offset-y="14.13"><line
 marker-end="url(#arrowhead)" x1="0" y1="0" x2="10" y2="10"></line></g></svg></pre>
<pre><svg id="diagram-2" xmlns="http://www.w3.org/2000/svg" role="img"
 aria-labelledby="chart-title-diagram-2 chart-desc-diagram-2"><title
 id="chart-title-diagram-2">Twee</title><desc id="chart-desc-diagram-2"></desc><style>
#diagram-2 :root{--mermaid-font-family:Arial;}#diagram-2 #arrowhead path{fill:#333;}</style><defs><marker id="arrowhead"><path
 d="M 0 0 L 10 5"></path></marker></defs><g class="node" label-offset-y="12.49"><line
 marker-end="url(#arrowhead)" x1="0" y1="0" x2="10" y2="10"></line></g></svg></pre>
</body></html>
"""


def build_steps() -> list[dict]:
    workflow = yaml.safe_load(BUILD_WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["build"]["steps"]


def step_names() -> list[str]:
    return [step.get("name") for step in build_steps()]


def normalize(html: str) -> str:
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / "snapshot.html"
        target.write_text(html, encoding="utf-8")
        subprocess.run(
            ["node", str(NORMALIZER), str(target)],
            check=True,
            capture_output=True,
        )
        return target.read_text(encoding="utf-8")


class MermaidSvgNormalizationTest(unittest.TestCase):
    def test_build_normalizes_before_validation(self) -> None:
        names = step_names()

        self.assertIn(
            "Normaliseer mermaid-diagrammen in snapshot",
            names,
            "De build moet de mermaid-SVG normaliseren voordat de HTML wordt gevalideerd.",
        )
        self.assertLess(
            names.index("Normaliseer mermaid-diagrammen in snapshot"),
            names.index("Prepare publication for validation"),
            "Normaliseren moet gebeuren voordat het publicatiepakket wordt samengesteld.",
        )
        self.assertGreater(
            names.index("Normaliseer mermaid-diagrammen in snapshot"),
            names.index("Generate HTML snapshot"),
            "Normaliseren kan pas nadat ReSpec de snapshot heeft gegenereerd.",
        )

    def test_normalizer_comes_from_central_tooling_checkout(self) -> None:
        names = step_names()
        checkout = next(step for step in build_steps() if step.get("name") == "Checkout workflow tooling")

        self.assertLess(
            names.index("Checkout workflow tooling"),
            names.index("Normaliseer mermaid-diagrammen in snapshot"),
            "De centrale hulpbestanden moeten zijn uitgecheckt voordat er genormaliseerd wordt.",
        )
        self.assertEqual(checkout["with"]["repository"], "${{ steps.tooling.outputs.repository }}")
        self.assertEqual(checkout["with"]["ref"], "${{ steps.tooling.outputs.ref }}")
        self.assertIn(".github/mermaid-svg", checkout["with"]["sparse-checkout"])

    def test_duplicate_mermaid_ids_become_unique(self) -> None:
        result = normalize(FIXTURE)

        duplicates = [
            identifier
            for identifier, count in Counter(ID_ATTRIBUTE.findall(result)).items()
            if count > 1
        ]
        self.assertEqual([], duplicates, "vnu meldt dubbele id's als fout.")

    def test_references_follow_the_renamed_ids(self) -> None:
        result = normalize(FIXTURE)

        self.assertIn('<marker id="diagram-1-arrowhead">', result)
        self.assertIn('<marker id="diagram-2-arrowhead">', result)
        self.assertIn("url(#diagram-1-arrowhead)", result)
        self.assertIn("url(#diagram-2-arrowhead)", result)
        self.assertIn("#diagram-1 #diagram-1-arrowhead path", result)
        self.assertNotIn("url(#arrowhead)", result)

    def test_no_reference_is_left_dangling(self) -> None:
        result = normalize(FIXTURE)

        identifiers = set(ID_ATTRIBUTE.findall(result))
        references = set(re.findall(r"url\(#([^)]+)\)", result))
        references |= set(re.findall(r'(?:xlink:)?href="#([^"]+)"', result))

        self.assertEqual(set(), references - identifiers)

    def test_unique_ids_and_respec_anchors_are_left_alone(self) -> None:
        result = normalize(FIXTURE)

        # Deze id's zijn al uniek en mogen dus niet worden herschreven; anders
        # breken permalinks naar secties en figuren.
        self.assertIn('id="diagram-1"', result)
        self.assertIn('id="chart-title-diagram-1"', result)
        self.assertIn(
            'aria-labelledby="chart-title-diagram-1 chart-desc-diagram-1"', result
        )

    def test_invalid_mermaid_layout_attributes_are_removed(self) -> None:
        result = normalize(FIXTURE)

        self.assertNotIn("label-offset-y", result)

    def test_normalization_is_idempotent(self) -> None:
        once = normalize(FIXTURE)
        self.assertEqual(once, normalize(once))


class MermaidContentPreservationTest(unittest.TestCase):
    def with_content(self, content):
        return FIXTURE.replace('</defs>', '</defs>' + content)

    def test_visible_labels_and_attribute_text_are_preserved(self):
        content = '<text aria-label="Verwijzing #arrowhead">Verwijzing #arrowhead</text>'
        result = normalize(self.with_content(content))
        self.assertEqual(2, result.count(content))
        self.assertIn('id="diagram-1-arrowhead"', result)

    def test_external_urls_are_preserved_and_local_hrefs_follow_ids(self):
        content = ('<a href="https://example.org/guide#arrowhead">Handleiding</a>'
                   '<use href="#arrowhead"></use><use xlink:href="#arrowhead"></use>'
                   '<path style="filter:url(https://example.org/guide#arrowhead)"></path>')
        result = normalize(self.with_content(content))
        self.assertEqual(4, result.count('https://example.org/guide#arrowhead'))
        self.assertIn('href="#diagram-1-arrowhead"', result)
        self.assertIn('xlink:href="#diagram-2-arrowhead"', result)

    def test_css_pseudoclasses_classes_and_strings(self):
        result = normalize(self.with_content('<style>'
            '#arrowhead:hover, #arrowhead.active, :is(#arrowhead){fill:#fff;'
            'content:"#arrowhead";filter:url("#arrowhead")}'
            '@media print {#arrowhead.active {stroke:red}}'
            '</style>'))
        self.assertIn('#diagram-1-arrowhead:hover', result)
        self.assertIn('#diagram-2-arrowhead.active', result)
        self.assertIn(':is(#diagram-1-arrowhead)', result)
        self.assertIn('content:"#arrowhead"', result)
        self.assertNotIn('url("#arrowhead")', result)

    def test_css_attribute_selectors_follow_local_id_attributes(self):
        result = normalize(self.with_content('<style>'
            '[id="arrowhead"], [href="#arrowhead"] {fill:red}'
            '[href="https://example.org/#arrowhead"] {fill:blue}'
            '</style>'))
        self.assertIn('[id="diagram-1-arrowhead"]', result)
        self.assertIn('[href="#diagram-2-arrowhead"]', result)
        self.assertIn('[href="https://example.org/#arrowhead"]', result)

    def test_css_custom_properties_contain_real_local_urls(self):
        result = normalize(self.with_content('<path style="--end:url(#arrowhead);'
            'marker-end:var(--end)"></path><style>#arrowhead{--end:url(#arrowhead)}</style>'))
        self.assertNotIn('url(#arrowhead)', result)
        self.assertIn('--end:url(#diagram-1-arrowhead)', result)

    def test_mermaid_inside_a_non_mermaid_svg_is_processed(self):
        inner = self.with_content('')
        source = ('<svg id="outer-brand"><foreignObject>' + inner +
                  '</foreignObject><path fill="#fff"></path></svg>')
        result = normalize(source)
        self.assertIn('<svg id="outer-brand">', result)
        self.assertIn('<path fill="#fff"></path>', result)
        self.assertIn('id="diagram-1-arrowhead"', result)
        self.assertNotIn('label-offset-y', result)

    def test_color_values_are_not_fragment_references(self):
        result = normalize(self.with_content('<path id="fff" fill="#fff" '
            'stroke="#fff" style="fill:#fff;filter:url(#fff)"></path>'))
        self.assertEqual(2, result.count('fill="#fff"'))
        self.assertEqual(2, result.count('stroke="#fff"'))
        self.assertEqual(2, result.count('fill:#fff'))
        self.assertIn('url(#diagram-1-fff)', result)

    def test_non_mermaid_svgs_are_byte_identical(self):
        ordinary = ('<svg id="brand-one"><defs><path id="fff"></path></defs>'
                    '<path fill="#fff" label-offset-x="2"></path></svg>'
                    '<svg id="brand-two"><path id="fff" fill="#fff"></path></svg>')
        self.assertEqual(ordinary, normalize(ordinary))
        self.assertIn(ordinary, normalize(self.with_content('') + ordinary))

    def test_script_comments_and_data_images_are_not_svg_elements(self):
        inert = ('<!-- <svg id="diagram-8"><path id="arrowhead"></path></svg> -->'
                 '<script>const example = `<svg id="diagram-9"><path id="arrowhead" '
                 'label-offset-y="3">#arrowhead</path></svg>`;</script>'
                 '<img src="data:image/svg+xml;base64,PHN2Zy8+" alt="diagram">')
        self.assertIn(inert, normalize(FIXTURE + inert))

    def test_aria_tokens_quoted_urls_and_nested_svg(self):
        content = ('<svg><title id="nested-title">Nested</title><desc id="nested-desc">Info</desc>'
                   '<use href="#arrowhead" aria-labelledby="nested-title nested-desc" '
                   'aria-describedby="nested-desc" style="marker-end: url( &quot;#arrowhead&quot; )">'
                   '</use></svg>')
        result = normalize(self.with_content(content))
        self.assertIn('aria-labelledby="diagram-1-nested-title diagram-1-nested-desc"', result)
        self.assertIn('aria-describedby="diagram-2-nested-desc"', result)
        self.assertNotIn('&quot;#arrowhead&quot;', result)
        self.assertEqual(result, normalize(result))

    def test_css_escaped_ids_and_html_entities(self):
        content = (r'<path id="node.part:1"></path><style>'
                   r'#node\.part\:1:hover &gt; path {fill:red}'
                   r'</style><use href="#node.part:1"></use>')
        result = normalize(self.with_content(content))
        self.assertIn(r'#diagram-1-node\.part\:1:hover', result)
        self.assertIn('href="#diagram-2-node.part:1"', result)

    def test_single_quoted_attributes_and_unique_new_ids(self):
        source = self.with_content('<path id="taken"></path><use href="#taken"></use>')
        source = source.replace('"', "'") + '<section id="diagram-1-taken"></section>'
        result = normalize(source)
        self.assertIn('id="diagram-1-taken-2"', result)
        self.assertIn('href="#diagram-1-taken-2"', result)
        self.assertIn('<section id="diagram-1-taken"></section>', result)
        self.assertNotIn('label-offset-y', result)

    def test_ambiguous_duplicates_within_one_diagram_fail_without_writing(self):
        source = self.with_content('<path id="arrowhead"></path>')
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'snapshot.html'
            target.write_text(source)
            result = subprocess.run(['node', str(NORMALIZER), str(target)],
                                    capture_output=True, text=True)
            self.assertNotEqual(0, result.returncode)
            self.assertIn('Dubbele id binnen Mermaid-diagram', result.stderr)
            self.assertEqual(source, target.read_text())

    def test_mermaid_container_without_generated_diagram_id(self):
        source = ('<div class="mermaid">' + FIXTURE.split('<pre>')[1].split('</pre>')[0]
                  .replace('diagram-1', 'custom-diagram') + '</div><p id="arrowhead">Anchor</p>')
        result = normalize(source)
        self.assertIn('id="custom-diagram-arrowhead"', result)
        self.assertIn('<p id="arrowhead">Anchor</p>', result)


class MermaidProductionFixtureTest(unittest.TestCase):
    def test_sensordata_sequence_and_flowcharts(self):
        source = (REPOSITORY_ROOT / 'tests/fixtures/mermaid/sensordata.html').read_text()
        self.assertEqual(13, sum(count > 1 for count in Counter(ID_ATTRIBUTE.findall(source)).values()))
        result = normalize(source)
        self.assertEqual([], [identifier for identifier, count in
                             Counter(ID_ATTRIBUTE.findall(result)).items() if count > 1])
        self.assertNotIn('label-offset-', result)
        refs = set(re.findall(r'url\(#([^)]+)\)', result))
        refs |= set(re.findall(r'(?:xlink:)?href="#([^"]+)"', result))
        self.assertEqual(set(), refs - set(ID_ATTRIBUTE.findall(result)))
        self.assertEqual(result, normalize(result))

    def test_respec_mermaid_1_3_data_images_are_byte_identical(self):
        source = (REPOSITORY_ROOT / 'tests/fixtures/mermaid/data-image.html').read_text()
        self.assertIn('data:image/svg+xml;base64,', source)
        self.assertEqual(source, normalize(source))

    def test_sparse_tooling_checkout_forms_a_runnable_normalizer(self):
        # Een documentrepository zonder eigen .github-hulpbestanden: alleen de
        # sparse checkout van het template mag nodig zijn om te normaliseren.
        checkout = next(step for step in build_steps() if step.get('name') == 'Checkout workflow tooling')
        sparse_paths = checkout['with']['sparse-checkout'].split()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'document'
            tooling = root / '.nl-respec-tooling'
            root.mkdir()
            for name in sparse_paths:
                shutil.copytree(REPOSITORY_ROOT / name, tooling / name,
                                ignore=shutil.ignore_patterns('node_modules'))
            target = root / 'snapshot.html'
            target.write_text(FIXTURE)
            step = next(step for step in build_steps() if
                        step.get('name') == 'Normaliseer mermaid-diagrammen in snapshot')
            subprocess.run(['bash', '-c', step['run']], cwd=root,
                           env={**os.environ, 'npm_config_offline': 'true', 'TOOLING_DIR': str(tooling)},
                           check=True, capture_output=True)
            self.assertEqual(normalize(FIXTURE), target.read_text())


class MermaidVisualWorkflowTest(unittest.TestCase):
    def test_visual_head_is_normalized_and_committed_base_is_preserved(self):
        workflow = yaml.safe_load((REPOSITORY_ROOT / '.github/workflows/visual-regression-reusable.yml').read_text())
        step = next(step for step in workflow['jobs']['visual-regression']['steps']
                    if step.get('name') == 'Prepare ReSpec snapshots')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            head = root / 'comparison/head'
            base = root / 'comparison/base'
            head.mkdir(parents=True)
            base.mkdir(parents=True)
            # De normalizer komt uit de tooling-checkout, niet uit de documentrepository.
            template = root / 'comparison/template'
            shutil.copytree(REPOSITORY_ROOT / '.github/mermaid-svg', template / '.github/mermaid-svg',
                            ignore=shutil.ignore_patterns('node_modules'))
            (template / '.github/workflows').mkdir(parents=True)
            shutil.copyfile(NORMALIZER, template / '.github/workflows' / NORMALIZER.name)
            (head / 'index.html').write_text(FIXTURE)
            (base / 'snapshot.html').write_text(FIXTURE)
            # Alleen de externe ReSpec-renderer vervangen: de echte shellstap,
            # dependency-installatie en normalizer worden uitgevoerd.
            binary = root / 'bin'
            binary.mkdir()
            renderer = binary / 'npx'
            renderer.write_text('#!/bin/bash\ncp "$SOURCE" "$SNAPSHOT"\n')
            renderer.chmod(0o755)
            subprocess.run(['bash', '-c', step['run']], cwd=root, check=True, capture_output=True,
                           env={**os.environ, 'GITHUB_WORKSPACE': str(root), 'WORK_DIR': 'comparison',
                                'SOURCE': 'index.html', 'SNAPSHOT': 'snapshot.html',
                                'PATH': str(binary) + os.pathsep + os.environ['PATH'],
                                'npm_config_offline': 'true'})
            self.assertEqual(FIXTURE, (base / 'snapshot.html').read_text())
            self.assertEqual(normalize(FIXTURE), (head / 'snapshot.html').read_text())


if __name__ == "__main__":
    unittest.main()
