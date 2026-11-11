# Excel 字段映射

每个 SKU 一行；缺少 SKU 的 SPU 仍保留一行基本信息。JSONL 保留接口完整原始记录。

| 列 | 名称 | 来源或处理 |
| --- | --- | --- |
| 1 | SPU编码 | `spuId（文本）` |
| 2 | 商品名称 | `spuName` |
| 3 | 商品类型 | `specType：1 单规格、2 多规格` |
| 4 | 后台商品类目 | `backendCategory.categoryCodePath / categoryCode` |
| 5 | 品牌名称 | `brand.brandName` |
| 6 | 产地 | `productPlace / originPlace` |
| 7 | 店内分类 | `storeFrontCategoryList[].storeCategoryList[].name` |
| 8 | SKU编码 | `skus[].skuId（文本）` |
| 9 | 规格名称 | `skus[].specName` |
| 10 | 商品条码 | `skus[].upcList（文本）` |
| 11 | 货品单位 | `skus[].saleUnit` |
| 12 | 重量 | `skus[].weight` |
| 13 | 重量单位 | `skus[].weightUnit` |
| 14 | 箱重换算 | `skus[].cartonMeasureConvertFactorList[].basicUnitConvertFactor（首个非空值）` |
| 15 | 总部零售价 | `skus[].suggestPrice.tenantSuggestPrice.unifiedSuggestPrice` |
| 16 | 基础价 | `skus[].basicPrice` |
| 17 | 在售状态 | `skus[].onlineStatus：1 在售；0/2 下架；其他枚举原样` |
| 18 | 美团闪购类目 | `spuChannelInfoList[channelId=100].categoryCodePath` |
| 19 | 饿了么类目 | `spuChannelInfoList[channelId=200].categoryCodePath` |
| 20 | 京东类目 | `spuChannelInfoList[channelId=300].categoryCodePath` |
| 21 | 京东品牌名称 | `spuChannelInfoList[channelId=300].brandInfo.brandName` |
| 22 | 渠道销售属性 | `skus[].skuChannelInfoList[].saleAttrValueList` |
| 23 | SPU标签 | `labelList` |
| 24 | SKU标签 | `skus[].skuLabelList` |
| 25 | 覆盖门店数 | `skus[].coverageInfo.storeCoverage：covered/total` |
| 26 | 是否有图 | `picUrlList 是否非空` |
| 27 | 不符渠道规则类型 | `abnormalCodeList（保留原编码）` |
| 28 | 不符渠道规则备注 | `abnormalMarkMsg / abnormalTips` |
| 29 | 必卖 | `mustSale：1 是、2 否` |
| 30 | 库存自动上架 | `stockAutoShelf：0 否、1 是` |
| 31 | 商品卖点 | `sellPoint` |
| 32 | 商品描述 | `description` |
| 33 | 主图数 | `picUrlList 条数` |
| 34 | 主图URL | `picUrlList` |
| 35 | 详情图数 | `picContentList 条数` |
| 36 | 详情图URL | `picContentList` |
| 37 | 特殊图数 | `有 URL 的 mtSpecialPictureList 条数` |
| 38 | 配料图(type5) | `mtSpecialPictureList[pictureType=5] 的首个 URL` |
| 39 | 特殊图明细 | `mtSpecialPictureList 的类型/标题与 URL` |
| 40 | 视频URL | `videoInfo.videoUrl` |
| 41 | 外部编码 | `skus[].externalCode（接口有值时）` |
| 42 | 保质期(天) | `skus[].expirationDays` |
| 43 | 创建时间(UTC) | `createTime：毫秒转 UTC` |
| 44 | 更新时间(UTC) | `updateTime：毫秒转 UTC` |

价格按接口原始数值写入，不做未验证的分/元换算；0 是有效值。缺失值留空。
品牌、类目和图片均只读取原有字段，不更改平台商品资料。

Excel 会移除 XML 不允许的控制字符；JSONL 原值保持完整。特殊图中的类型标签仅用于展示，未知类型保留 `typeN`。
