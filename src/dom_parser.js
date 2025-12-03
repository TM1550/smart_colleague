// dom_parser.js - Обновленная версия для лучшей интеграции
const fs = require('fs');
const { JSDOM } = require('jsdom');

// Устанавливаем кодировку для вывода
process.stdout.setDefaultEncoding('utf8');

function parseDOM(htmlPath) {
    try {
        // Читаем файл с указанием кодировки UTF-8
        const html = fs.readFileSync(htmlPath, 'utf8');
        const dom = new JSDOM(html);
        const document = dom.window.document;
        
        function elementToTree(element, depth = 0) {
            // Ограничиваем глубину для больших документов
            if (depth > 10) {
                return {
                    tagName: element.tagName ? element.tagName.toLowerCase() : '...',
                    depthLimit: true
                };
            }
            
            // Обрабатываем текстовое содержимое
            let textContent = '';
            if (element.textContent) {
                textContent = element.textContent.trim().replace(/\s+/g, ' ').substring(0, 200);
            }
            
            const elementInfo = {
                tagName: element.tagName ? element.tagName.toLowerCase() : '',
                attributes: {},
                children: [],
                textContent: textContent,
                elementCount: 0
            };
            
            // Собираем атрибуты
            if (element.attributes) {
                for (let attr of element.attributes) {
                    elementInfo.attributes[attr.name] = attr.value;
                }
            }
            
            // Обрабатываем детей
            if (element.children && element.children.length > 0) {
                for (let child of element.children) {
                    const childTree = elementToTree(child, depth + 1);
                    elementInfo.children.push(childTree);
                    elementInfo.elementCount += 1 + (childTree.elementCount || 0);
                }
            }
            
            return elementInfo;
        }
        
        return elementToTree(document.documentElement);
    } catch (error) {
        return { error: error.message };
    }
}

// Основная функция анализа
function analyzeDOM(htmlFiles) {
    const results = [];
    const summary = {
        totalPages: htmlFiles.length,
        totalElements: 0,
        elementsByType: {},
        interactiveElements: 0
    };

    htmlFiles.forEach(filePath => {
        try {
            const domTree = parseDOM(filePath);
            const analysis = {
                file: filePath,
                domTree: domTree,
                stats: {
                    totalElements: domTree.elementCount || 0,
                    interactiveElements: countInteractiveElements(domTree)
                }
            };
            
            results.push(analysis);
            
            // Обновляем суммарную статистику
            summary.totalElements += analysis.stats.totalElements;
            summary.interactiveElements += analysis.stats.interactiveElements;
            
        } catch (error) {
            results.push({
                file: filePath,
                error: error.message
            });
        }
    });

    return {
        analyzedAt: new Date().toISOString(),
        summary: summary,
        results: results
    };
}

function countInteractiveElements(node) {
    let count = 0;
    const interactiveTags = ['button', 'a', 'input', 'select', 'textarea', 'form'];
    
    if (interactiveTags.includes(node.tagName)) {
        count += 1;
    }
    
    for (let child of node.children) {
        count += countInteractiveElements(child);
    }
    
    return count;
}

// Получение путей файлов из временного файла
const tempFile = process.argv[2];
try {
    const htmlFiles = JSON.parse(fs.readFileSync(tempFile, 'utf8'));
    const analysisResult = analyzeDOM(htmlFiles);

    // Сохранение результата в JSON с поддержкой Unicode
    fs.writeFileSync('dom_analysis.json', JSON.stringify(analysisResult, null, 2), 'utf8');
    
    // Также выводим в stdout для возможности захвата вывода
    console.log(JSON.stringify({
        status: 'success',
        message: 'DOM analysis completed',
        filesAnalyzed: htmlFiles.length,
        outputFile: 'dom_analysis.json'
    }));
    
} catch (error) {
    console.error(JSON.stringify({
        status: 'error',
        error: error.message
    }));
    process.exit(1);
}