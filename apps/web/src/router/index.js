import { createRouter, createWebHistory } from 'vue-router';
import AdminLayout from '../layouts/AdminLayout.vue';
import AgentPlannerView from '../views/admin/AgentPlannerView.vue';
import DashboardView from '../views/admin/DashboardView.vue';
import InventoryView from '../views/admin/InventoryView.vue';
import ProcurementView from '../views/admin/ProcurementView.vue';
import KioskView from '../views/kiosk/KioskView.vue';
const router = createRouter({
    history: createWebHistory(),
    routes: [
        { path: '/', redirect: '/admin/agent' },
        {
            path: '/admin',
            component: AdminLayout,
            children: [
                { path: 'dashboard', component: DashboardView },
                { path: 'agent', component: AgentPlannerView },
                { path: 'inventory', component: InventoryView },
                { path: 'procurement', component: ProcurementView },
            ],
        },
        { path: '/kiosk', component: KioskView },
    ],
});
export default router;
