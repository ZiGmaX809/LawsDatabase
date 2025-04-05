<template>
  <div class="container mx-auto p-4 max-w-3xl">
    <h1 class="text-2xl font-bold mb-6">LPR利息计算器</h1>
    
    <div class="bg-white rounded-lg shadow p-6 mb-6">
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">贷款金额 (元)</label>
          <input
            v-model.number="store.amount"
            type="number"
            class="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500"
          />
        </div>

        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">LPR期限</label>
          <select
            v-model="store.term"
            class="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500"
          >
            <option value="one_year">一年期</option>
            <option value="five_year">五年期以上</option>
          </select>
        </div>

        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">开始日期</label>
          <input
            v-model="store.startDate"
            type="date"
            class="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500"
          />
        </div>

        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">结束日期</label>
          <input
            v-model="store.endDate"
            type="date"
            class="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500"
          />
        </div>

        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">LPR倍数</label>
          <input
            v-model.number="store.multiple"
            type="number"
            min="1"
            step="0.1"
            class="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500"
          />
        </div>

        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">年度天数</label>
          <select
            v-model.number="store.dayCount"
            class="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500"
          >
            <option :value="365">365天</option>
            <option :value="360">360天</option>
          </select>
        </div>
      </div>

      <div class="mt-4">
        <button
          @click="store.calculateInterest"
          class="w-full bg-indigo-600 text-white py-2 px-4 rounded-md hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500"
        >
          计算利息
        </button>
      </div>
    </div>

    <div v-if="store.calculations.length > 0" class="bg-white rounded-lg shadow p-6">
      <h2 class="text-lg font-semibold mb-4">计算结果</h2>
      <div class="overflow-x-auto">
        <table class="min-w-full divide-y divide-gray-200">
          <thead class="bg-gray-50">
            <tr>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">开始日期</th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">结束日期</th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">天数</th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">适用LPR</th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">利息金额</th>
            </tr>
          </thead>
          <tbody class="bg-white divide-y divide-gray-200">
            <tr v-for="(calc, index) in store.calculations" :key="index">
              <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{{ calc.start_date }}</td>
              <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{{ calc.end_date }}</td>
              <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{{ calc.days }}</td>
              <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{{ (calc.rate * 100).toFixed(2) }}%</td>
              <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{{ calc.interest.toFixed(2) }}</td>
            </tr>
          </tbody>
          <tfoot class="bg-gray-50">
            <tr>
              <td colspan="4" class="px-6 py-3 text-left text-sm font-medium text-gray-500">总计</td>
              <td class="px-6 py-3 text-left text-sm font-medium text-gray-900">{{ store.totalInterest.toFixed(2) }}</td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useCalculatorStore } from '@/stores/calculator'

const store = useCalculatorStore()
</script>