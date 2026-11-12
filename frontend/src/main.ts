import {createApp} from 'vue'
import {createPinia} from 'pinia'
import {createRouter,createWebHistory} from 'vue-router'
import App from './App.vue'
import './style.css'

const router=createRouter({history:createWebHistory(),routes:[
 {path:'/',component:()=>import('./pages/Dashboard.vue')}, {path:'/projects',component:()=>import('./pages/Projects.vue')},
 {path:'/projects/:id/:tab?',component:()=>import('./pages/Workspace.vue')}, {path:'/models',component:()=>import('./pages/Models.vue')},
 {path:'/candidates',component:()=>import('./pages/VideoCandidates.vue')},
 {path:'/voice',component:()=>import('./pages/VoiceWorkbench.vue')},
 {path:'/runs',component:()=>import('./pages/Runs.vue')},
 {path:'/:section',component:()=>import('./pages/Hub.vue')}, {path:'/:pathMatch(.*)*',redirect:'/'}
]})
createApp(App).use(createPinia()).use(router).mount('#app')
