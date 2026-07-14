<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div class="card">
      <div class="card-header">
        <h3 class="card-title">{{ t('restocking.budgetLabel') }}</h3>
      </div>
      <div class="budget-slider-row">
        <input
          type="range"
          class="budget-slider"
          min="0"
          max="100000"
          step="500"
          v-model.number="budget"
        />
        <div class="budget-value">{{ currencySymbol }}{{ budget.toLocaleString() }}</div>
      </div>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <div v-if="successMessage" class="success-banner">{{ successMessage }}</div>

      <div class="stats-grid">
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.allocated') }}</div>
          <div class="stat-value">{{ currencySymbol }}{{ allocatedCost.toLocaleString() }}</div>
        </div>
        <div class="stat-card success">
          <div class="stat-label">{{ t('restocking.remaining') }}</div>
          <div class="stat-value">{{ currencySymbol }}{{ remainingBudget.toLocaleString() }}</div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.title') }} ({{ recommendations.length }})</h3>
          <button class="btn-primary" :disabled="submitting || checkedItems.length === 0" @click="placeOrder">
            {{ submitting ? t('restocking.placingOrder') : t('restocking.placeOrder') }}
          </button>
        </div>

        <div v-if="recommendations.length === 0" class="loading">{{ t('restocking.noRecommendations') }}</div>
        <div v-else class="table-container">
          <table>
            <thead>
              <tr>
                <th>
                  <input type="checkbox" :checked="allChecked" @change="toggleSelectAll" />
                </th>
                <th>{{ t('restocking.table.sku') }}</th>
                <th>{{ t('restocking.table.name') }}</th>
                <th>{{ t('restocking.table.category') }}</th>
                <th>{{ t('restocking.table.quantityOnHand') }}</th>
                <th>{{ t('restocking.table.reorderPoint') }}</th>
                <th>{{ t('restocking.table.trend') }}</th>
                <th>{{ t('restocking.table.suggestedQuantity') }}</th>
                <th>{{ t('restocking.table.suggestedCost') }}</th>
                <th>{{ t('restocking.table.leadTimeDays') }}</th>
                <th>{{ t('restocking.table.reason') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in recommendations" :key="item.sku">
                <td>
                  <input type="checkbox" v-model="checkedMap[item.sku]" />
                </td>
                <td>{{ item.sku }}</td>
                <td>{{ translateProductName(item.name) }}</td>
                <td>{{ item.category }}</td>
                <td>{{ item.quantity_on_hand }}</td>
                <td>{{ item.reorder_point }}</td>
                <td>
                  <span v-if="item.trend" :class="['badge', item.trend.toLowerCase()]">
                    {{ t(`trends.${item.trend.toLowerCase()}`) }}
                  </span>
                  <span v-else>-</span>
                </td>
                <td>{{ item.suggested_quantity }}</td>
                <td>{{ currencySymbol }}{{ item.suggested_cost.toLocaleString() }}</td>
                <td>{{ item.lead_time_days }}</td>
                <td>{{ item.reason }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, watch, onMounted } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency, translateProductName } = useI18n()

    const currencySymbol = computed(() => {
      return currentCurrency.value === 'JPY' ? '¥' : '$'
    })

    const budget = ref(20000)
    const loading = ref(true)
    const error = ref(null)
    const submitting = ref(false)
    const successMessage = ref(null)
    const recommendations = ref([])
    const checkedMap = ref({})

    // Debounce timer id for slider-driven reloads (no @vueuse/core dependency in this project)
    let debounceTimer = null

    const loadRecommendations = async () => {
      try {
        loading.value = true
        error.value = null
        const response = await api.getRestockRecommendations(budget.value)
        recommendations.value = response.recommendations

        // Pre-check all recommended items by default
        const nextChecked = {}
        for (const item of response.recommendations) {
          nextChecked[item.sku] = true
        }
        checkedMap.value = nextChecked
      } catch (err) {
        error.value = 'Failed to load restocking recommendations: ' + err.message
      } finally {
        loading.value = false
      }
    }

    // Debounce budget changes so slider dragging doesn't spam the API
    watch(budget, () => {
      if (debounceTimer) clearTimeout(debounceTimer)
      debounceTimer = setTimeout(() => {
        loadRecommendations()
      }, 400)
    })

    const checkedItems = computed(() => {
      return recommendations.value.filter(item => checkedMap.value[item.sku])
    })

    const allocatedCost = computed(() => {
      return checkedItems.value.reduce((sum, item) => sum + item.suggested_cost, 0)
    })

    const remainingBudget = computed(() => {
      return budget.value - allocatedCost.value
    })

    const allChecked = computed(() => {
      return recommendations.value.length > 0 &&
        recommendations.value.every(item => checkedMap.value[item.sku])
    })

    const toggleSelectAll = () => {
      const shouldCheck = !allChecked.value
      const nextChecked = {}
      for (const item of recommendations.value) {
        nextChecked[item.sku] = shouldCheck
      }
      checkedMap.value = nextChecked
    }

    const placeOrder = async () => {
      if (checkedItems.value.length === 0) return

      submitting.value = true
      successMessage.value = null
      error.value = null

      try {
        const items = checkedItems.value.map(item => ({
          sku: item.sku,
          quantity: item.suggested_quantity
        }))

        await api.submitRestockOrder({
          budget: budget.value,
          items
        })

        successMessage.value = t('restocking.orderSuccess')
        await loadRecommendations()
      } catch (err) {
        error.value = 'Failed to place restocking order: ' + err.message
      } finally {
        submitting.value = false
      }
    }

    onMounted(loadRecommendations)

    return {
      t,
      budget,
      loading,
      error,
      submitting,
      successMessage,
      recommendations,
      checkedMap,
      checkedItems,
      allocatedCost,
      remainingBudget,
      allChecked,
      toggleSelectAll,
      placeOrder,
      currencySymbol,
      translateProductName
    }
  }
}
</script>

<style scoped>
.budget-slider-row {
  display: flex;
  align-items: center;
  gap: 1.5rem;
}

.budget-slider {
  flex: 1;
  height: 6px;
  border-radius: 3px;
  background: #e2e8f0;
  accent-color: #2563eb;
  cursor: pointer;
}

.budget-value {
  font-size: 1.25rem;
  font-weight: 700;
  color: #0f172a;
  min-width: 140px;
  text-align: right;
}

.success-banner {
  background: #d1fae5;
  border: 1px solid #a7f3d0;
  color: #065f46;
  padding: 1rem;
  border-radius: 8px;
  margin-bottom: 1.25rem;
  font-size: 0.938rem;
}

.btn-primary {
  padding: 0.625rem 1.25rem;
  background: #2563eb;
  color: white;
  border: none;
  border-radius: 8px;
  font-weight: 600;
  font-size: 0.875rem;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-primary:hover:not(:disabled) {
  background: #1d4ed8;
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
