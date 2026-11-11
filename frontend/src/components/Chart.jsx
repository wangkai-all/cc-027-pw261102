import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'

const AXIS_STYLE = {
  axisLine: { lineStyle: { color: '#c3c2b7' } },
  axisTick: { show: false },
  axisLabel: { color: '#898781', fontSize: 11 },
  splitLine: { lineStyle: { color: '#e1e0d9', type: 'dashed' } },
}

/** 轻量 ECharts 封装：option 变化时重绘，自适应宽度。 */
export default function Chart({ option, height = 320, className = '' }) {
  const ref = useRef(null)
  const chartRef = useRef(null)

  useEffect(() => {
    const chart = echarts.init(ref.current)
    chartRef.current = chart
    const onResize = () => chart.resize()
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      chart.dispose()
    }
  }, [])

  useEffect(() => {
    if (chartRef.current && option) {
      chartRef.current.setOption(option, { notMerge: true })
    }
  }, [option])

  return <div ref={ref} className={`chart ${className}`} style={{ height }} />
}

export const baseTooltip = {
  trigger: 'axis',
  backgroundColor: '#fcfcfb',
  borderColor: '#c3c2b7',
  textStyle: { color: '#0b0b0b', fontSize: 12 },
  axisPointer: { type: 'shadow', shadowStyle: { color: 'rgba(42,120,214,0.08)' } },
}

export const lineAxis = (extra = {}) => ({
  tooltip: baseTooltip,
  grid: { left: 48, right: 20, top: 42, bottom: 56 },
  xAxis: { type: 'category', ...AXIS_STYLE, ...(extra.xAxis || {}) },
  yAxis: { type: 'value', ...AXIS_STYLE, ...(extra.yAxis || {}) },
  legend: { top: 6, textStyle: { color: '#52514e', fontSize: 12 } },
  ...extra.rest,
})

export const COLORS = {
  rop: '#2a78d6',
  cycle: '#eb6834',
  aqua: '#1baf7a',
  yellow: '#eda100',
  violet: '#6250d6',
  lost: '#d03b3b',
  scrap: '#ec835a',
  good: '#0ca30c',
}
