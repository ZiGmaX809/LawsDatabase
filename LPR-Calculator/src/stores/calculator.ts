import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'

interface LPRData {
  date: string
  one_year_rate: number
  five_year_rate: number
}

interface Calculation {
  start_date: string
  end_date: string
  days: number
  rate: number
  interest: number
}

export const useCalculatorStore = defineStore('calculator', () => {
  const amount = ref(1000000)
  const startDate = ref(new Date().toISOString().split('T')[0])
  const endDate = ref(new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString().split('T')[0])
  const term = ref<'one_year' | 'five_year'>('one_year')
  const multiple = ref(1)
  const dayCount = ref(365)
  const lprData = ref<LPRData[]>([])
  const calculations = ref<Calculation[]>([])
  const totalInterest = ref(0)

  const fetchLPRData = async () => {
    try {
      // 模拟数据，实际应用中应从API获取
      lprData.value = [
        { date: '2023-01-01', one_year_rate: 0.0385, five_year_rate: 0.045 },
        { date: '2023-06-20', one_year_rate: 0.037, five_year_rate: 0.042 },
        { date: '2023-12-20', one_year_rate: 0.0365, five_year_rate: 0.0415 }
      ]
    } catch (error) {
      console.error('获取LPR数据失败:', error)
    }
  }

  const calculateInterest = () => {
    if (!lprData.value.length) {
      alert('请先获取LPR数据')
      return
    }

    const start = new Date(startDate.value)
    const end = new Date(endDate.value)
    
    if (start >= end) {
      alert('结束日期必须晚于开始日期')
      return
    }

    const rateColumn = term.value === 'one_year' ? 'one_year_rate' : 'five_year_rate'
    const rateChanges = lprData.value
      .map(item => ({
        date: new Date(item.date),
        rate: item[rateColumn]
      }))
      .filter(item => item.date > start && item.date <= end)
      .sort((a, b) => a.date.getTime() - b.date.getTime())

    const calculationsResult: Calculation[] = []
    let currentDate = start
    let currentRate = lprData.value
      .filter(item => new Date(item.date) <= start)
      .sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime())[0][rateColumn]

    // 处理每个利率变更区间
    for (const change of rateChanges) {
      const days = Math.floor((change.date.getTime() - currentDate.getTime()) / (1000 * 60 * 60 * 24))
      const interest = amount.value * currentRate * multiple.value * days / dayCount.value
      
      calculationsResult.push({
        start_date: currentDate.toISOString().split('T')[0],
        end_date: new Date(change.date.getTime() - 1).toISOString().split('T')[0],
        days,
        rate: currentRate,
        interest
      })

      currentDate = change.date
      currentRate = change.rate
    }

    // 处理最后一段
    const finalDays = Math.floor((end.getTime() - currentDate.getTime()) / (1000 * 60 * 60 * 24)) + 1
    const finalInterest = amount.value * currentRate * multiple.value * finalDays / dayCount.value
    
    calculationsResult.push({
      start_date: currentDate.toISOString().split('T')[0],
      end_date: end.toISOString().split('T')[0],
      days: finalDays,
      rate: currentRate,
      interest: finalInterest
    })

    calculations.value = calculationsResult
    totalInterest.value = calculationsResult.reduce((sum, calc) => sum + calc.interest, 0)
  }

  // 初始化时获取LPR数据
  fetchLPRData()

  return {
    amount,
    startDate,
    endDate,
    term,
    multiple,
    dayCount,
    lprData,
    calculations,
    totalInterest,
    fetchLPRData,
    calculateInterest
  }
})