"""渠道层 CSV enrich（非自动爬虫）。"""

from sources.base import SourceDescriptor

CHANNEL_SOURCE = SourceDescriptor("channel_csv", "channel", "电商渠道 CSV 导入", active=True)
