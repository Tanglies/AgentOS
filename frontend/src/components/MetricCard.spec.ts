import { mount } from '@vue/test-utils'
import MetricCard from './MetricCard.vue'

describe('MetricCard', () => {
  it('renders label and value', () => {
    const wrapper = mount(MetricCard, { props: { label: 'Total Runs', value: '284', trend: '+12%' } })
    expect(wrapper.text()).toContain('Total Runs')
    expect(wrapper.text()).toContain('284')
    expect(wrapper.text()).toContain('+12%')
  })
})