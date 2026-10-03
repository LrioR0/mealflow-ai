import { onMounted, ref } from 'vue';
import { apiRequest } from '../../api/client';
const menu = ref(null);
const rating = ref(0);
const tags = ref([]);
const comment = ref('');
const submitted = ref(false);
const loading = ref(false);
const error = ref('');
const tagOptions = ['太咸', '太辣', '份量少', '温度低', '很喜欢'];
onMounted(async () => {
    try {
        menu.value = await apiRequest('/kiosk/current-menu');
    }
    catch (reason) {
        error.value = reason instanceof Error ? reason.message : '菜单加载失败';
    }
});
function toggleTag(tag) {
    tags.value = tags.value.includes(tag) ? tags.value.filter((item) => item !== tag) : [...tags.value, tag];
}
function reset() {
    rating.value = 0;
    tags.value = [];
    comment.value = '';
    submitted.value = false;
}
async function submit() {
    if (!rating.value)
        return;
    loading.value = true;
    error.value = '';
    try {
        await apiRequest('/kiosk/feedback', {
            method: 'POST',
            body: JSON.stringify({
                meal_service_id: 'demo-lunch',
                meal_plan_id: 'demo-plan',
                rating: rating.value,
                tags: tags.value,
                comment: comment.value || null,
            }),
        });
        submitted.value = true;
        window.setTimeout(reset, 3000);
    }
    catch (reason) {
        error.value = reason instanceof Error ? reason.message : '提交失败';
    }
    finally {
        loading.value = false;
    }
}
debugger; /* PartiallyEnd: #3632/scriptSetup.vue */
const __VLS_ctx = {};
let __VLS_components;
let __VLS_directives;
__VLS_asFunctionalElement(__VLS_intrinsicElements.main, __VLS_intrinsicElements.main)({
    ...{ class: "kiosk-shell" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.header, __VLS_intrinsicElements.header)({
    ...{ class: "kiosk-header" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "brand" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
    ...{ class: "brand-mark" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({});
__VLS_asFunctionalElement(__VLS_intrinsicElements.strong, __VLS_intrinsicElements.strong)({});
__VLS_asFunctionalElement(__VLS_intrinsicElements.small, __VLS_intrinsicElements.small)({});
__VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({});
if (__VLS_ctx.submitted) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.section, __VLS_intrinsicElements.section)({
        ...{ class: "thank-you" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "thank-icon" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.h1, __VLS_intrinsicElements.h1)({});
    __VLS_asFunctionalElement(__VLS_intrinsicElements.p, __VLS_intrinsicElements.p)({});
}
else {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.section, __VLS_intrinsicElements.section)({
        ...{ class: "kiosk-content" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({});
    __VLS_asFunctionalElement(__VLS_intrinsicElements.p, __VLS_intrinsicElements.p)({
        ...{ class: "eyebrow" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.h1, __VLS_intrinsicElements.h1)({});
    if (__VLS_ctx.menu) {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
            ...{ class: "kiosk-menu-grid" },
        });
        for (const [dish] of __VLS_getVForSourceType((__VLS_ctx.menu.menu))) {
            __VLS_asFunctionalElement(__VLS_intrinsicElements.article, __VLS_intrinsicElements.article)({
                key: (dish.name),
            });
            __VLS_asFunctionalElement(__VLS_intrinsicElements.strong, __VLS_intrinsicElements.strong)({});
            (dish.name);
            __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({});
            (dish.kcal_per_serving);
            __VLS_asFunctionalElement(__VLS_intrinsicElements.small, __VLS_intrinsicElements.small)({});
            (dish.allergens.length ? `过敏原：${dish.allergens.join('、')}` : '无已知主要过敏原');
        }
    }
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "feedback-card" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.p, __VLS_intrinsicElements.p)({
        ...{ class: "eyebrow" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.h2, __VLS_intrinsicElements.h2)({});
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "rating-row" },
    });
    for (const [value] of __VLS_getVForSourceType((5))) {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
            ...{ onClick: (...[$event]) => {
                    if (!!(__VLS_ctx.submitted))
                        return;
                    __VLS_ctx.rating = value;
                } },
            key: (value),
            ...{ class: ({ active: __VLS_ctx.rating === value }) },
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({});
        (['很差', '一般', '还行', '满意', '很好'][value - 1]);
        __VLS_asFunctionalElement(__VLS_intrinsicElements.strong, __VLS_intrinsicElements.strong)({});
        (value);
    }
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "tag-row" },
    });
    for (const [tag] of __VLS_getVForSourceType((__VLS_ctx.tagOptions))) {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
            ...{ onClick: (...[$event]) => {
                    if (!!(__VLS_ctx.submitted))
                        return;
                    __VLS_ctx.toggleTag(tag);
                } },
            key: (tag),
            ...{ class: ({ active: __VLS_ctx.tags.includes(tag) }) },
        });
        (tag);
    }
    __VLS_asFunctionalElement(__VLS_intrinsicElements.textarea, __VLS_intrinsicElements.textarea)({
        value: (__VLS_ctx.comment),
        maxlength: "300",
        rows: "2",
        placeholder: "选填：还有什么想告诉我们？",
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
        ...{ onClick: (__VLS_ctx.submit) },
        ...{ class: "kiosk-submit" },
        disabled: (!__VLS_ctx.rating || __VLS_ctx.loading),
    });
    (__VLS_ctx.loading ? '正在提交…' : '提交匿名反馈');
    if (__VLS_ctx.error) {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.p, __VLS_intrinsicElements.p)({
            ...{ class: "error-message" },
        });
        (__VLS_ctx.error);
    }
}
/** @type {__VLS_StyleScopedClasses['kiosk-shell']} */ ;
/** @type {__VLS_StyleScopedClasses['kiosk-header']} */ ;
/** @type {__VLS_StyleScopedClasses['brand']} */ ;
/** @type {__VLS_StyleScopedClasses['brand-mark']} */ ;
/** @type {__VLS_StyleScopedClasses['thank-you']} */ ;
/** @type {__VLS_StyleScopedClasses['thank-icon']} */ ;
/** @type {__VLS_StyleScopedClasses['kiosk-content']} */ ;
/** @type {__VLS_StyleScopedClasses['eyebrow']} */ ;
/** @type {__VLS_StyleScopedClasses['kiosk-menu-grid']} */ ;
/** @type {__VLS_StyleScopedClasses['feedback-card']} */ ;
/** @type {__VLS_StyleScopedClasses['eyebrow']} */ ;
/** @type {__VLS_StyleScopedClasses['rating-row']} */ ;
/** @type {__VLS_StyleScopedClasses['active']} */ ;
/** @type {__VLS_StyleScopedClasses['tag-row']} */ ;
/** @type {__VLS_StyleScopedClasses['active']} */ ;
/** @type {__VLS_StyleScopedClasses['kiosk-submit']} */ ;
/** @type {__VLS_StyleScopedClasses['error-message']} */ ;
var __VLS_dollars;
const __VLS_self = (await import('vue')).defineComponent({
    setup() {
        return {
            menu: menu,
            rating: rating,
            tags: tags,
            comment: comment,
            submitted: submitted,
            loading: loading,
            error: error,
            tagOptions: tagOptions,
            toggleTag: toggleTag,
            submit: submit,
        };
    },
});
export default (await import('vue')).defineComponent({
    setup() {
        return {};
    },
});
; /* PartiallyEnd: #4569/main.vue */
