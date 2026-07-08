(function () {
    function stripHtml(value) {
        return String(value || "")
            .replace(/<[^>]*>/g, "")
            .trim();
    }

    function sanitizeFileName(value) {
        return String(value || "export")
            .replace(/[\\/:*?"<>|]+/g, " ")
            .replace(/\s+/g, " ")
            .trim();
    }

    function sanitizeSheetName(value) {
        const name = String(value || "Export")
            .replace(/[\\/?*:[\]]+/g, " ")
            .replace(/\s+/g, " ")
            .trim();
        return (name || "Export").slice(0, 31);
    }

    function getColumnDefinition(column) {
        return column.getDefinition ? column.getDefinition() : column;
    }

    function getSubColumns(column) {
        const definition = getColumnDefinition(column);
        return column.getSubColumns ? column.getSubColumns() : (definition.columns || []);
    }

    function isExportableLeaf(column) {
        const definition = getColumnDefinition(column);
        return Boolean(definition.field) && definition.download !== false && definition.formatter !== "buttonCross";
    }

    function collectLeafColumns(columns, parentTitle = "") {
        const result = [];
        columns.forEach((column) => {
            const definition = getColumnDefinition(column);
            const title = stripHtml(definition.title);
            const fullTitle = parentTitle && title ? `${parentTitle} - ${title}` : (title || parentTitle);
            const subColumns = getSubColumns(column);

            if (subColumns && subColumns.length > 0) {
                result.push(...collectLeafColumns(subColumns, fullTitle));
                return;
            }

            if (!isExportableLeaf(column)) {
                return;
            }

            result.push({
                title: fullTitle || definition.field,
                field: definition.field,
            });
        });
        return result;
    }

    function flattenRows(rows) {
        const output = [];
        const stack = [];
        for (let index = rows.length - 1; index >= 0; index -= 1) {
            stack.push({row: rows[index], level: 0});
        }

        while (stack.length > 0) {
            const {row, level} = stack.pop();
            const rowCopy = {...row, __tree_level: level};
            delete rowCopy._children;
            output.push(rowCopy);

            if (Array.isArray(row._children) && row._children.length > 0) {
                for (let index = row._children.length - 1; index >= 0; index -= 1) {
                    stack.push({row: row._children[index], level: level + 1});
                }
            }
        }

        return output;
    }

    function countExportableLeaves(columns) {
        let count = 0;
        columns.forEach((column) => {
            const subColumns = getSubColumns(column);
            if (subColumns && subColumns.length > 0) {
                count += countExportableLeaves(subColumns);
            } else if (isExportableLeaf(column)) {
                count += 1;
            }
        });
        return count;
    }

    function columnDepth(columns) {
        let depth = 1;
        columns.forEach((column) => {
            const subColumns = getSubColumns(column);
            if (subColumns && subColumns.length > 0 && countExportableLeaves(subColumns) > 0) {
                depth = Math.max(depth, 1 + columnDepth(subColumns));
            }
        });
        return depth;
    }

    function buildHeaderInfo(columns) {
        const depth = columnDepth(columns);
        const rows = Array.from({length: depth}, () => []);
        const merges = [];
        const leaves = [];

        function setHeaderCell(rowIndex, columnIndex, value) {
            rows[rowIndex][columnIndex] = value;
        }

        function walk(currentColumns, level, startColumnIndex) {
            let currentColumnIndex = startColumnIndex;

            currentColumns.forEach((column) => {
                const definition = getColumnDefinition(column);
                const title = stripHtml(definition.title) || definition.field || "";
                const subColumns = getSubColumns(column);
                const leafCount = subColumns && subColumns.length > 0
                    ? countExportableLeaves(subColumns)
                    : 0;

                if (leafCount > 0) {
                    const groupStart = currentColumnIndex;
                    currentColumnIndex = walk(subColumns, level + 1, currentColumnIndex);
                    const groupEnd = currentColumnIndex - 1;
                    setHeaderCell(level, groupStart, title);
                    if (groupEnd > groupStart) {
                        merges.push({
                            startRow: level,
                            endRow: level,
                            startCol: groupStart,
                            endCol: groupEnd,
                        });
                    }
                    return;
                }

                if (!isExportableLeaf(column)) {
                    return;
                }

                setHeaderCell(level, currentColumnIndex, title);
                leaves.push({
                    title: title || definition.field,
                    field: definition.field,
                });

                if (level < depth - 1) {
                    merges.push({
                        startRow: level,
                        endRow: depth - 1,
                        startCol: currentColumnIndex,
                        endCol: currentColumnIndex,
                    });
                }
                currentColumnIndex += 1;
            });

            return currentColumnIndex;
        }

        walk(columns, 0, 0);

        rows.forEach((row) => {
            for (let index = 0; index < leaves.length; index += 1) {
                if (row[index] === undefined) {
                    row[index] = "";
                }
            }
        });

        return {headerRows: rows, merges, leaves};
    }

    function getExportData(table, options = {}) {
        const exportColumns = options.columns || table.getColumns();
        const headerInfo = buildHeaderInfo(exportColumns);
        const sourceRows = options.rows || (typeof table.getData === "function" ? table.getData("active") : []);
        return {
            columns: headerInfo.leaves,
            headerRows: headerInfo.headerRows,
            merges: headerInfo.merges,
            rows: flattenRows(sourceRows),
        };
    }

    function cellValue(row, column) {
        const value = row[column.field];
        if (value === null || value === undefined || value === "") {
            return "";
        }
        return value;
    }

    function escapeHtml(value) {
        return String(value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function escapeXml(value) {
        return String(value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&apos;");
    }

    function buildHtmlTable(table, title, options = {}) {
        const {columns, headerRows, merges, rows} = getExportData(table, options);
        const headerHtml = headerRows
            .map((headerRow, rowIndex) => {
                const cells = headerRow
                    .map((cellTitle, columnIndex) => {
                        const merge = merges.find((item) => item.startRow === rowIndex && item.startCol === columnIndex);
                        const covered = merges.some((item) => (
                            rowIndex >= item.startRow
                            && rowIndex <= item.endRow
                            && columnIndex >= item.startCol
                            && columnIndex <= item.endCol
                            && !(item.startRow === rowIndex && item.startCol === columnIndex)
                        ));
                        if (covered) {
                            return "";
                        }

                        const rowSpan = merge ? merge.endRow - merge.startRow + 1 : 1;
                        const colSpan = merge ? merge.endCol - merge.startCol + 1 : 1;
                        const rowSpanAttr = rowSpan > 1 ? ` rowspan="${rowSpan}"` : "";
                        const colSpanAttr = colSpan > 1 ? ` colspan="${colSpan}"` : "";
                        return `<th${rowSpanAttr}${colSpanAttr}>${escapeHtml(cellTitle)}</th>`;
                    })
                    .join("");
                return `<tr>${cells}</tr>`;
            })
            .join("");
        const bodyHtml = rows
            .map((row) => {
                const cells = columns
                    .map((column, index) => {
                        const value = cellValue(row, column);
                        const padding = index === 0 && row.__tree_level
                            ? ` style="padding-left:${row.__tree_level * 22 + 8}px"`
                            : "";
                        return `<td${padding}>${escapeHtml(value)}</td>`;
                    })
                    .join("");
                return `<tr>${cells}</tr>`;
            })
            .join("");

        return `<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>${escapeHtml(title)}</title>
    <style>
        @page { margin: 10mm; }
        body { font-family: Arial, sans-serif; color: #1f2d38; }
        h1 { font-size: 20px; margin: 0 0 16px; }
        table { border-collapse: collapse; width: 100%; font-size: 11px; }
        th, td { border: 1px solid #9aa8b2; padding: 6px 8px; vertical-align: top; }
        th { background: #eff5f9; font-weight: 700; }
    </style>
</head>
<body>
    <h1>${escapeHtml(title)}</h1>
    <table>
        <thead>${headerHtml}</thead>
        <tbody>${bodyHtml}</tbody>
    </table>
</body>
</html>`;
    }

    function downloadBlob(content, fileName, mimeType) {
        const blob = new Blob([content], {type: mimeType});
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = sanitizeFileName(fileName);
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
    }

    function columnName(index) {
        let name = "";
        let value = index + 1;
        while (value > 0) {
            const remainder = (value - 1) % 26;
            name = String.fromCharCode(65 + remainder) + name;
            value = Math.floor((value - remainder) / 26);
        }
        return name;
    }

    function isNumericValue(value) {
        return typeof value === "number" || /^-?\d+([.,]\d+)?$/.test(String(value).trim());
    }

    function worksheetCell(value, rowIndex, columnIndex) {
        const ref = `${columnName(columnIndex)}${rowIndex + 1}`;
        if (value === null || value === undefined || value === "") {
            return `<c r="${ref}"/>`;
        }
        if (isNumericValue(value)) {
            return `<c r="${ref}"><v>${String(value).replace(",", ".")}</v></c>`;
        }
        const preserveSpace = /^\s|\s$/.test(String(value)) ? ' xml:space="preserve"' : "";
        return `<c r="${ref}" t="inlineStr"><is><t${preserveSpace}>${escapeXml(value)}</t></is></c>`;
    }

    function buildWorksheetXml(table, options = {}) {
        const {columns, headerRows, merges, rows} = getExportData(table, options);
        const allRows = [
            ...headerRows,
            ...rows.map((row) => columns.map((column, index) => {
                const value = cellValue(row, column);
                return index === 0 && row.__tree_level ? `${" ".repeat(row.__tree_level * 4)}${value}` : value;
            })),
        ];
        const maxColumnWidth = columns.map((column, index) => {
            let maxLength = 10;
            allRows.forEach((row) => {
                const valueLength = String(row[index] || "").length;
                if (valueLength > maxLength) {
                    maxLength = valueLength;
                }
            });
            return Math.min(maxLength + 2, 60);
        });
        const colsXml = maxColumnWidth
            .map((width, index) => `<col min="${index + 1}" max="${index + 1}" width="${width}" customWidth="1"/>`)
            .join("");
        const rowsXml = allRows
            .map((row, rowIndex) => {
                const cellsXml = row
                    .map((value, columnIndex) => worksheetCell(value, rowIndex, columnIndex))
                    .join("");
                return `<row r="${rowIndex + 1}">${cellsXml}</row>`;
            })
            .join("");
        const mergeCellsXml = merges.length > 0
            ? `<mergeCells count="${merges.length}">${merges
                .map((merge) => {
                    const start = `${columnName(merge.startCol)}${merge.startRow + 1}`;
                    const end = `${columnName(merge.endCol)}${merge.endRow + 1}`;
                    return `<mergeCell ref="${start}:${end}"/>`;
                })
                .join("")}</mergeCells>`
            : "";

        return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
    <cols>${colsXml}</cols>
    <sheetData>${rowsXml}</sheetData>
    ${mergeCellsXml}
</worksheet>`;
    }

    const crcTable = (() => {
        const table = new Uint32Array(256);
        for (let index = 0; index < 256; index += 1) {
            let value = index;
            for (let bit = 0; bit < 8; bit += 1) {
                value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
            }
            table[index] = value >>> 0;
        }
        return table;
    })();

    function crc32(bytes) {
        let crc = -1;
        for (let index = 0; index < bytes.length; index += 1) {
            crc = (crc >>> 8) ^ crcTable[(crc ^ bytes[index]) & 0xff];
        }
        return (crc ^ -1) >>> 0;
    }

    function writeUint16(output, value) {
        output.push(value & 0xff, (value >>> 8) & 0xff);
    }

    function writeUint32(output, value) {
        output.push(value & 0xff, (value >>> 8) & 0xff, (value >>> 16) & 0xff, (value >>> 24) & 0xff);
    }

    function dosDateTime(date = new Date()) {
        return {
            time: (date.getHours() << 11) | (date.getMinutes() << 5) | Math.floor(date.getSeconds() / 2),
            day: ((date.getFullYear() - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate(),
        };
    }

    function createZip(files) {
        const encoder = new TextEncoder();
        const output = [];
        const centralDirectory = [];
        const now = dosDateTime();
        let offset = 0;

        files.forEach((file) => {
            const nameBytes = encoder.encode(file.name);
            const dataBytes = encoder.encode(file.content);
            const checksum = crc32(dataBytes);

            const localHeader = [];
            writeUint32(localHeader, 0x04034b50);
            writeUint16(localHeader, 20);
            writeUint16(localHeader, 0x0800);
            writeUint16(localHeader, 0);
            writeUint16(localHeader, now.time);
            writeUint16(localHeader, now.day);
            writeUint32(localHeader, checksum);
            writeUint32(localHeader, dataBytes.length);
            writeUint32(localHeader, dataBytes.length);
            writeUint16(localHeader, nameBytes.length);
            writeUint16(localHeader, 0);
            appendBytes(output, localHeader);
            appendBytes(output, nameBytes);
            appendBytes(output, dataBytes);

            const centralHeader = [];
            writeUint32(centralHeader, 0x02014b50);
            writeUint16(centralHeader, 20);
            writeUint16(centralHeader, 20);
            writeUint16(centralHeader, 0x0800);
            writeUint16(centralHeader, 0);
            writeUint16(centralHeader, now.time);
            writeUint16(centralHeader, now.day);
            writeUint32(centralHeader, checksum);
            writeUint32(centralHeader, dataBytes.length);
            writeUint32(centralHeader, dataBytes.length);
            writeUint16(centralHeader, nameBytes.length);
            writeUint16(centralHeader, 0);
            writeUint16(centralHeader, 0);
            writeUint16(centralHeader, 0);
            writeUint16(centralHeader, 0);
            writeUint32(centralHeader, 0);
            writeUint32(centralHeader, offset);
            appendBytes(centralDirectory, centralHeader);
            appendBytes(centralDirectory, nameBytes);

            offset = output.length;
        });

        const centralDirectoryOffset = output.length;
        appendBytes(output, centralDirectory);
        writeUint32(output, 0x06054b50);
        writeUint16(output, 0);
        writeUint16(output, 0);
        writeUint16(output, files.length);
        writeUint16(output, files.length);
        writeUint32(output, centralDirectory.length);
        writeUint32(output, centralDirectoryOffset);
        writeUint16(output, 0);

        return new Uint8Array(output);
    }

    function appendBytes(target, source) {
        for (let index = 0; index < source.length; index += 1) {
            target.push(source[index]);
        }
    }

    function buildXlsx(table, sheetName, options = {}) {
        const safeSheetName = sanitizeSheetName(sheetName);
        return createZip([
            {
                name: "[Content_Types].xml",
                content: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
    <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
    <Default Extension="xml" ContentType="application/xml"/>
    <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
    <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>`,
            },
            {
                name: "_rels/.rels",
                content: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
    <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>`,
            },
            {
                name: "xl/workbook.xml",
                content: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
    <sheets><sheet name="${escapeXml(safeSheetName)}" sheetId="1" r:id="rId1"/></sheets>
</workbook>`,
            },
            {
                name: "xl/_rels/workbook.xml.rels",
                content: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
    <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>`,
            },
            {
                name: "xl/worksheets/sheet1.xml",
                content: buildWorksheetXml(table, options),
            },
        ]);
    }

    function exportExcel(table, fileName, sheetName, options = {}) {
        const xlsx = buildXlsx(table, sheetName || fileName, options);
        downloadBlob(
            xlsx,
            `${sanitizeFileName(fileName)}.xlsx`,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        );
    }

    function exportPdf(table, fileName, title, options = {}) {
        const html = buildHtmlTable(table, title || fileName, options);
        const printWindow = window.open(`${window.location.pathname}#export-pdf`, "_blank");
        if (!printWindow) {
            throw new Error("Браузер заблокировал окно печати. Разрешите всплывающие окна для сайта.");
        }
        printWindow.document.open();
        printWindow.document.write(html);
        printWindow.document.close();
        printWindow.document.title = sanitizeFileName(fileName);
        printWindow.focus();
        printWindow.print();
    }

    window.ProjectBudgetTableExport = {
        exportExcel,
        exportPdf,
        sanitizeFileName,
    };
})();
