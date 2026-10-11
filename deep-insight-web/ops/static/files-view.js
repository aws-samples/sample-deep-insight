// ==================== Files view ====================
// A job's files, shared by the job list (side panel) and the job page:
// input data, result documents (the report first), images, then every
// generated file (collapsed). Needs admin-i18n.js (t).

var FilesView = (function() {
    var IMAGE_EXT = ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'];
    var RESULT_EXT = ['.docx', '.pdf', '.pptx', '.xlsx'];

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text != null) node.textContent = text;
        return node;
    }

    function hasExt(name, exts) {
        var lower = name.toLowerCase();
        return exts.some(function(ext) { return lower.endsWith(ext); });
    }

    function formatSize(bytes) {
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / 1024 / 1024).toFixed(1) + ' MB';
    }

    function fileUrl(jobId, area, name, download) {
        var path = name.split('/').map(encodeURIComponent).join('/');
        return '/admin/api/jobs/' + encodeURIComponent(jobId) + '/files/' + area + '/' + path + (download ? '?download=true' : '');
    }

    async function fetchFiles(jobId) {
        try {
            var res = await fetch('/admin/api/jobs/' + encodeURIComponent(jobId) + '/files');
            var data = await res.json();
            return data.success ? data : { error: true };
        } catch (e) {
            return { error: true };
        }
    }

    // The job's report: the record's pick, else the first .docx (the Lambda's
    // rule; jobs recorded before their artifacts reached S3 have none)
    function reportName(job, files) {
        if (job && job.report_filename) return job.report_filename;
        var docx = (files.artifacts || []).find(function(f) { return f.name.toLowerCase().endsWith('.docx'); });
        return docx ? docx.name : '';
    }

    function title(text, count) {
        return el('div', 'fv-title', text + ' (' + count + ')');
    }

    function fileList(container, jobId, area, files) {
        if (!files.length) {
            container.appendChild(el('div', 'fv-empty', t('files_none')));
            return;
        }
        files.forEach(function(f) {
            var row = el('div', 'fv-row');
            var link = el('a', 'fv-link', f.name);
            link.href = fileUrl(jobId, area, f.name, true);
            row.appendChild(link);
            row.appendChild(el('span', 'fv-size', formatSize(f.size)));
            container.appendChild(row);
        });
    }

    function render(container, jobId, job, files) {
        if (files.error) {
            container.appendChild(el('div', 'fv-empty', t('files_load_error')));
            return;
        }
        var artifacts = files.artifacts || [];
        var report = reportName(job, files);

        // 1. Input data
        container.appendChild(title(t('files_input'), files.input.length));
        fileList(container, jobId, 'input', files.input);

        // 2. Result documents, the report first
        var results = artifacts.filter(function(f) { return hasExt(f.name, RESULT_EXT); });
        results.sort(function(a, b) { return (b.name === report) - (a.name === report); });
        container.appendChild(title(t('files_results'), results.length));
        if (results.length) {
            var cards = el('div', 'fv-results');
            results.forEach(function(f) {
                var card = el('a', 'fv-result' + (f.name === report ? ' primary' : ''));
                card.href = fileUrl(jobId, 'artifacts', f.name, true);
                card.title = f.name;
                card.appendChild(el('span', 'fv-result-icon', f.name.split('.').pop().toUpperCase()));
                var meta = el('span', 'fv-result-meta');
                meta.appendChild(el('span', 'fv-result-name', f.name));
                meta.appendChild(el('span', 'fv-size', formatSize(f.size) + (f.name === report ? ' · ' + t('files_report_badge') : '')));
                card.appendChild(meta);
                card.appendChild(el('span', 'fv-download', '↓'));
                cards.appendChild(card);
            });
            container.appendChild(cards);
        } else {
            container.appendChild(el('div', 'fv-empty', t('files_none')));
        }

        // 3. Images: charts are saved as .png and .svg; show one per chart
        var names = {};
        artifacts.forEach(function(f) { names[f.name] = true; });
        var images = artifacts.filter(function(f) {
            if (!hasExt(f.name, IMAGE_EXT)) return false;
            return !(f.name.toLowerCase().endsWith('.svg') && names[f.name.replace(/\.svg$/i, '.png')]);
        });
        container.appendChild(title(t('files_images'), images.length));
        if (images.length) {
            var grid = el('div', 'fv-images');
            images.forEach(function(f) {
                var tile = el('a', 'fv-image');
                tile.href = fileUrl(jobId, 'artifacts', f.name, false);
                tile.target = '_blank';
                tile.rel = 'noopener';
                var img = el('img');
                img.src = tile.href;
                img.loading = 'lazy';
                img.alt = f.name;
                tile.appendChild(img);
                tile.appendChild(el('span', null, f.name));
                grid.appendChild(tile);
            });
            container.appendChild(grid);
        } else {
            container.appendChild(el('div', 'fv-empty', t('files_none')));
        }

        // 4. Every generated file (code, cache, intermediate results), collapsed
        var all = el('details', 'fv-all');
        all.appendChild(el('summary', 'fv-title', t('files_all') + ' (' + artifacts.length + ')'));
        fileList(all, jobId, 'artifacts', artifacts);
        container.appendChild(all);
    }

    return { fetchFiles: fetchFiles, render: render, reportName: reportName, fileUrl: fileUrl };
})();
