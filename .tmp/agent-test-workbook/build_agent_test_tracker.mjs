import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = "D:/Agent/mealflow-ai/docs";
const outputPath = `${outputDir}/MealFlow Agent系统测试缺陷台账.xlsx`;
const previewDir = "D:/Agent/mealflow-ai/.tmp/agent-test-workbook/previews";
const fontName = "Arial";
const green = "#0F5C52";
const greenLight = "#EAF4F1";
const headerGray = "#2F3B38";
const border = "#D9E1DE";

const workbook = Workbook.create();
const bugs = workbook.worksheets.add("缺陷台账");
const cases = workbook.worksheets.add("测试用例");
const guide = workbook.worksheets.add("字段说明");

function baseSheet(sheet, range) {
  sheet.showGridLines = false;
  sheet.getRange(range).format.font = { name: fontName, size: 10, color: "#243330" };
}

function styleTitle(sheet, range, value) {
  sheet.mergeCells(range);
  const cell = sheet.getRange(range);
  cell.values = [[value]];
  cell.format = {
    font: { name: fontName, size: 15, bold: true, color: "#172C27" },
    verticalAlignment: "center",
  };
  cell.format.rowHeight = 30;
}

function styleHeader(range) {
  range.format = {
    fill: headerGray,
    font: { name: fontName, size: 10, bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "all", style: "thin", color: "#FFFFFF" },
  };
  range.format.rowHeight = 32;
}

function styleTable(range) {
  range.format = {
    verticalAlignment: "top",
    wrapText: true,
    borders: { preset: "all", style: "thin", color: border },
  };
}

baseSheet(bugs, "A1:S30");
styleTitle(bugs, "A2:S2", "MealFlow Agent 系统测试缺陷台账");
bugs.getRange("A3:S3").merge();
bugs.getRange("A3").values = [["用于记录、筛选和跟踪测试过程中发现的问题。黄色单元格可由测试人员持续补充。"]];
bugs.getRange("A3").format = { font: { name: fontName, size: 9, italic: true, color: "#65736F" } };

const bugHeaders = [
  "Bug ID", "Bug 标题", "所在模块", "功能页面", "Bug 详情", "前置条件", "复现步骤", "预期结果", "实际结果", "严重等级", "Bug 类型", "影响范围", "附件截图", "状态", "提交人", "发现日期", "修复版本", "回归结果", "备注",
];
const bugRows = [
  [
    "INV-001", "无法创建无匹配的自定义食材", "冰箱库存", "冰箱库存 > 新增库存", "输入“牛排”等不在数据字典中的食材时，联想列表没有候选；保存时提示“请输入并选择一个已有食材”。", "已进入新增冰箱库存弹窗。", "1. 在食材名称输入牛排。\n2. 未出现候选项。\n3. 填写其他必填字段并保存。", "用户可明确创建自定义食材；创建后可正常入库并在后续 Agent 对话中被读取。", "无法保存，出现“请输入并选择一个已有食材”提示。", "P1", "功能", "阻断用户录入真实库存，Agent 无法依据该食材推荐。", "codex-clipboard-15d1b32c-958d-4ad4-8e43-87ca8f94e5e1.png", "新建", "Colin", new Date(2026, 9, 9), "", "未测试", ""],
  [
    "PANTRY-001", "默认常备料展示内部英文 key", "人员信息 > 厨房常备料", "人员信息", "开启默认库后，常备料标签直接展示 cooking_wine、dark_soy_sauce 等内部 key。", "默认厨房常备料库已启用。", "1. 进入人员信息页面。\n2. 查看厨房常备料标签。", "所有默认常备料展示可理解的中文名称，例如料酒、老抽、食用油。", "展示英文内部 key。", "P2", "展示", "降低可读性，用户无法准确理解家庭常备料配置。", "codex-clipboard-d0fb42ec-bfd3-453f-848a-2a19d9e2d24a.png", "新建", "Colin", new Date(2026, 9, 9), "", "未测试", ""],
  [
    "PANTRY-002", "自定义常备料缺少单独删除入口", "人员信息 > 厨房常备料", "人员信息", "添加黄油后仅能看到标签，界面未提供删除单项自定义常备料的操作。", "已新增并保存自定义常备料黄油。", "1. 新增黄油并保存。\n2. 尝试删除黄油。", "每项自定义常备料可单独删除；保存并刷新后不应恢复。", "未找到删除入口。", "P1", "交互", "错误配置无法自行清理，长期影响配餐和缺料判断。", "codex-clipboard-d0fb42ec-bfd3-453f-848a-2a19d9e2d24a.png", "新建", "Colin", new Date(2026, 9, 9), "", "未测试", ""],
  [
    "PANTRY-003", "关闭默认库后自定义项仍保留", "人员信息 > 厨房常备料", "人员信息", "关闭“启用默认库”后，默认项隐藏，而此前新增的黄油继续显示。", "默认库已启用且已新增自定义常备料黄油。", "1. 关闭启用默认库。\n2. 保存并查看标签。", "确认行为：默认库开关只影响默认常备料；家庭自定义项黄油继续保留，且应提供单独删除入口。", "黄油仍显示。", "P3", "预期确认", "无阻断；用于防止后续将正确行为误判为缺陷。", "codex-clipboard-42ea170f-1d01-4e63-866f-f58adcb1d760.png", "已确认", "Colin", new Date(2026, 9, 9), "不需要修复", "通过", "不是缺陷，保留为需求确认记录。"],
];
bugs.getRange("A5:S5").values = [bugHeaders];
bugs.getRange("A6:S9").values = bugRows;
styleHeader(bugs.getRange("A5:S5"));
styleTable(bugs.getRange("A6:S9"));
bugs.getRange("A6:S9").format.rowHeight = 74;
bugs.getRange("J6:J9").format.horizontalAlignment = "center";
bugs.getRange("N6:N9").format.horizontalAlignment = "center";
bugs.getRange("P6:P9").format.numberFormat = "yyyy-mm-dd";
bugs.getRange("O6:S30").format.fill = "#FFF8DC";
bugs.getRange("A5:S9").format.autofitColumns();

const bugWidths = [12, 24, 19, 22, 40, 28, 44, 40, 34, 10, 12, 34, 38, 12, 12, 14, 14, 12, 26];
bugWidths.forEach((width, index) => { bugs.getCell(0, index).format.columnWidth = width; });
bugs.freezePanes.freezeRows(5);
bugs.freezePanes.freezeColumns(2);
const bugTable = bugs.tables.add("A5:S9", true, "BugTrackerTable");
bugTable.showFilterButton = true;
bugTable.style = "TableStyleMedium2";
bugs.getRange("J6:J30").dataValidation = { rule: { type: "list", values: ["P0", "P1", "P2", "P3"] } };
bugs.getRange("K6:K30").dataValidation = { rule: { type: "list", values: ["功能", "交互", "数据", "展示", "兼容性", "性能", "预期确认"] } };
bugs.getRange("N6:N30").dataValidation = { rule: { type: "list", values: ["新建", "处理中", "待验证", "已关闭", "拒绝", "已确认"] } };
bugs.getRange("R6:R30").dataValidation = { rule: { type: "list", values: ["未测试", "通过", "失败", "不适用"] } };
bugs.getRange("J6:J30").conditionalFormats.add("containsText", { text: "P1", format: { fill: "#FCE8E6", font: { color: "#B42318", bold: true } } });
bugs.getRange("J6:J30").conditionalFormats.add("containsText", { text: "P2", format: { fill: "#FFF4D6", font: { color: "#8A5A00", bold: true } } });
bugs.getRange("N6:N30").conditionalFormats.add("containsText", { text: "新建", format: { fill: "#FCE8E6", font: { color: "#B42318" } } });
bugs.getRange("N6:N30").conditionalFormats.add("containsText", { text: "已关闭", format: { fill: "#EAF4F1", font: { color: green } } });

baseSheet(cases, "A1:L30");
styleTitle(cases, "A2:L2", "MealFlow Agent 系统测试用例");
cases.getRange("A3:L3").merge();
cases.getRange("A3").values = [["执行前先填写执行人和日期；实际结果与测试结果在执行后填写。"]];
cases.getRange("A3").format = { font: { name: fontName, size: 9, italic: true, color: "#65736F" } };
const caseHeaders = ["用例 ID", "所在模块", "测试场景", "前置条件", "测试步骤", "预期结果", "实际结果", "测试结果", "优先级", "执行人", "执行日期", "备注"];
const caseRows = [
  ["TC-INV-001", "冰箱库存", "已有食材联想与入库", "食材数据字典已加载。", "输入“牛”，从联想结果选择已有食材；填写数量后保存。", "出现匹配候选；选择后可保存；库存列表展示正确名称与单位。", "", "未执行", "P1", "", "", ""],
  ["TC-INV-002", "冰箱库存", "创建无匹配自定义食材", "打开新增库存弹窗。", "输入“牛排”；确认没有匹配候选后，完成类别、数量、单位、到期日并保存。", "可明确创建牛排；刷新后仍存在；后续 Agent 可读取该库存。", "", "未执行", "P1", "", "", ""],
  ["TC-INV-003", "冰箱库存", "库存字段校验", "打开新增库存弹窗。", "分别提交空名称、空类别、零或负数数量、空单位。", "阻止提交并在对应字段给出清晰提示，不生成库存数据。", "", "未执行", "P2", "", "", ""],
  ["TC-INV-004", "智能配餐 Agent", "Agent 读取自定义库存", "已创建并保存自定义食材牛排。", "进入智能配餐，询问“冰箱里有什么”。", "工具结果/回答中可看到牛排；不能将其忽略或误称不存在。", "", "未执行", "P1", "", "", ""],
  ["TC-PANTRY-001", "厨房常备料", "默认常备料中文展示", "启用默认库。", "进入人员信息并查看厨房常备料。", "展示中文名称，如盐、糖、食用油、料酒、老抽；不展示英文 key。", "", "未执行", "P2", "", "", ""],
  ["TC-PANTRY-002", "厨房常备料", "新增自定义常备料", "进入人员信息。", "新增“黄油”并保存，刷新页面。", "黄油持续展示为自定义常备料；不自动加入库存或采购清单。", "", "未执行", "P1", "", "", ""],
  ["TC-PANTRY-003", "厨房常备料", "默认库开关与自定义项保留", "默认库开启，且已新增黄油。", "关闭默认库并保存；重新进入页面。", "默认项隐藏；黄油保留。", "", "未执行", "P3", "", "", "预期确认"],
  ["TC-PANTRY-004", "厨房常备料", "删除自定义常备料", "已新增黄油。", "删除黄油，保存并刷新页面。", "黄油消失且不恢复；不影响默认库其他项。", "", "未执行", "P1", "", "", ""],
  ["TC-PANTRY-005", "智能配餐 Agent", "常备料参与饮食限制校验", "将某常备料设置为成员过敏或忌口。", "请求包含该常备料的菜谱/菜单建议。", "Agent 不应因食材属于常备料而绕过过敏或忌口限制。", "", "未执行", "P1", "", "", ""],
];
cases.getRange("A5:L5").values = [caseHeaders];
cases.getRange("A6:L14").values = caseRows;
styleHeader(cases.getRange("A5:L5"));
styleTable(cases.getRange("A6:L14"));
cases.getRange("A6:L14").format.rowHeight = 54;
cases.getRange("J6:L30").format.fill = "#FFF8DC";
const caseWidths = [14, 18, 26, 26, 42, 42, 34, 12, 10, 12, 14, 24];
caseWidths.forEach((width, index) => { cases.getCell(0, index).format.columnWidth = width; });
cases.getRange("K6:K30").format.numberFormat = "yyyy-mm-dd";
cases.freezePanes.freezeRows(5);
cases.freezePanes.freezeColumns(2);
const caseTable = cases.tables.add("A5:L14", true, "TestCasesTable");
caseTable.showFilterButton = true;
caseTable.style = "TableStyleMedium2";
cases.getRange("H6:H30").dataValidation = { rule: { type: "list", values: ["未执行", "通过", "失败", "阻塞"] } };
cases.getRange("I6:I30").dataValidation = { rule: { type: "list", values: ["P0", "P1", "P2", "P3"] } };
cases.getRange("H6:H30").conditionalFormats.add("containsText", { text: "通过", format: { fill: "#EAF4F1", font: { color: green, bold: true } } });
cases.getRange("H6:H30").conditionalFormats.add("containsText", { text: "失败", format: { fill: "#FCE8E6", font: { color: "#B42318", bold: true } } });
cases.getRange("H6:H30").conditionalFormats.add("containsText", { text: "阻塞", format: { fill: "#FFF4D6", font: { color: "#8A5A00", bold: true } } });

baseSheet(guide, "A1:D15");
styleTitle(guide, "A2:D2", "字段说明");
guide.getRange("A4:D4").values = [["字段", "填写说明", "可选值或示例", "注意事项"]];
const guideRows = [
  ["Bug ID", "缺陷唯一编号。", "INV-001、PANTRY-001", "按模块缩写加三位序号递增。"],
  ["严重等级", "衡量问题对用户和核心流程的影响。", "P0 阻断上线；P1 核心功能受阻；P2 明显体验问题；P3 低风险或预期确认。", "优先级不等同于修复难度。"],
  ["状态", "记录当前处理阶段。", "新建、处理中、待验证、已关闭、拒绝、已确认", "修复后先改为待验证，回归通过后再关闭。"],
  ["Bug 类型", "用于快速筛选问题性质。", "功能、交互、数据、展示、兼容性、性能、预期确认", "一个问题以主要类型为准。"],
  ["实际结果", "测试现场真实发生的结果。", "保存被拒绝，出现提示。", "不要写推测原因。"],
  ["附件截图", "关联复现证据。", "图片文件名或共享链接", "建议命名包含日期和模块。"],
  ["回归结果", "修复后重新执行对应测试用例的结果。", "未测试、通过、失败、不适用", "失败时新建后续缺陷或关联原缺陷。"],
];
guide.getRange("A5:D11").values = guideRows;
styleHeader(guide.getRange("A4:D4"));
styleTable(guide.getRange("A5:D11"));
guide.getRange("A5:D11").format.rowHeight = 38;
[18, 38, 60, 38].forEach((width, index) => { guide.getCell(0, index).format.columnWidth = width; });
guide.freezePanes.freezeRows(4);

for (const sheet of [bugs, cases, guide]) {
  sheet.tabColor = green;
}

workbook.recalculate();
await fs.mkdir(outputDir, { recursive: true });
await fs.mkdir(previewDir, { recursive: true });

const checks = await workbook.inspect({ kind: "table", range: "缺陷台账!A2:S9", include: "values,formulas", tableMaxRows: 12, tableMaxCols: 19 });
console.log(checks.ndjson);
const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 50 }, summary: "formula error scan" });
console.log(errors.ndjson);

for (const [sheetName, fileName] of [["缺陷台账", "bugs.png"], ["测试用例", "cases.png"], ["字段说明", "guide.png"]]) {
  const preview = await workbook.render({ sheetName, autoCrop: "all", scale: 1.25, format: "png" });
  await fs.writeFile(`${previewDir}/${fileName}`, new Uint8Array(await preview.arrayBuffer()));
}

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(`OUTPUT=${outputPath}`);
