function posSystem() {
    return {
        mobileTab: 'products',
        showCloseModal: false, showWeightModal: false, weightInput: '', tempProduct: null,
        searchQuery: '', searchResults: [], cart: [], topProducts: [],
        payWithCard: false, cashReceivedInput: '', cashDebtInput: '', 
        forceExit: false,
        
        showRechargeModal: false,
        servicesList: [],
        rechargeData: { product_id: '', amount: '' }, 
        
        init() {
            if (typeof autoAnimate !== 'undefined') autoAnimate(document.getElementById('top-products-grid'));
            this.fetchTopProducts();
            this.fetchServices(); 
            setInterval(() => this.fetchTopProducts(), 15000);
            this.$watch('payWithCard', value => { this.cashReceivedInput = ''; this.cashDebtInput = ''; });

            window.addEventListener('beforeunload', (e) => {
                if (this.cart.length > 0 && !this.forceExit) { e.preventDefault(); e.returnValue = ''; }
            });

            document.body.addEventListener('click', (e) => {
                const link = e.target.closest('a');
                if (link && link.href && !link.href.includes('#') && !link.href.includes('javascript') && !link.hasAttribute('download') && this.cart.length > 0) {
                    e.preventDefault();
                    Swal.fire({
                        title: '¿Abandonar Venta?', text: "Tienes productos en el carrito. Si sales, se perderá la venta actual.", icon: 'warning',
                        showCancelButton: true, confirmButtonColor: '#3e1717', cancelButtonColor: '#d33', confirmButtonText: 'Sí, salir', cancelButtonText: 'Quedarme', reverseButtons: true
                    }).then((result) => {
                        if (result.isConfirmed) { this.forceExit = true; window.location.href = link.href; }
                    });
                }
            });
        },

        async fetchServices() {
            try {
                const res = await fetch('/api/services/list/');
                if (res.ok) this.servicesList = await res.json();
            } catch (e) { console.error(e); }
        },

        openRechargeModal() {
            this.rechargeData = { product_id: '', amount: '' };
            this.showRechargeModal = true;
        },

        addRechargeToCart() {
            if (!this.rechargeData.product_id || !this.rechargeData.amount) {
                return Swal.fire('Error', 'Completa la compañía y el monto.', 'warning');
            }

            let srv = this.servicesList.find(s => s.id == this.rechargeData.product_id);
            
            this.cart.push({
                id: srv.id,
                name: `📱 ${srv.name}`,
                description: '', 
                price: parseFloat(this.rechargeData.amount),
                quantity: 1,
                max_stock: 999999, 
                stock: 999999,
                is_service: true,
                promo: null,
                promotions: []
            });

            this.showRechargeModal = false;
            const Toast = Swal.mixin({toast: true, position: 'top-end', showConfirmButton: false, timer: 1500});
            Toast.fire({icon: 'success', title: 'Servicio añadido'});
        },

        async fetchTopProducts() {
            try {
                const response = await fetch('/api/products/top/');
                if (response.ok) this.topProducts = await response.json();
            } catch (error) { console.error(error); }
        },

        async searchProducts(query) {
            this.searchQuery = query;
            if (query.length < 2 && isNaN(query)) { this.searchResults = []; return; }
            try {
                const response = await fetch(`/api/products/search/?q=${query}`);
                if(response.ok) this.searchResults = await response.json();
            } catch (error) { console.error(error); }
        },

        clearSearch() {
            this.searchQuery = '';
            document.getElementById('search-input').value = '';
            this.searchResults = [];
            document.getElementById('search-input').focus();
        },

        async initiateAddToCart(product) {
            if (product.is_service) {
                this.clearSearch();
                this.openRechargeModal();
                this.rechargeData.product_id = product.id;
                return;
            }

            if (product.stock <= 0) {
                Swal.fire({icon: 'error', title: 'Agotado', text: 'Sin stock disponible', timer: 1000, showConfirmButton: false});
                return;
            }
            
            if (product.is_weighted) {
                this.tempProduct = product;
                this.weightInput = '';
                this.showWeightModal = true;
                setTimeout(() => document.getElementById('weight-input-field').focus(), 100);
            } else { 
                await this.addToCart(product, 1); 
            }
        },

        async confirmWeight() {
            const weight = parseFloat(this.weightInput);
            if (!weight || weight <= 0) { Swal.fire('Error', 'Peso inválido', 'error'); return; }
            if (weight > this.tempProduct.stock) {
                Swal.fire('Error', `Solo tienes ${this.tempProduct.stock} kg`, 'warning');
                return;
            }
            await this.addToCart(this.tempProduct, weight);
            this.showWeightModal = false;
            this.tempProduct = null;
        },

        async addToCart(product, qty) {
            let depositToCharge = 0;

            // --- PREGUNTA POR EL ENVASE ---
            if (product.is_returnable) {
                const result = await Swal.fire({
                    title: '♻️ Producto Retornable',
                    text: '¿El cliente trajo el envase vacío?',
                    icon: 'question',
                    showDenyButton: true,
                    showCancelButton: true,
                    confirmButtonText: 'Sí, lo trajo',
                    denyButtonText: 'No (Cobrar Importe)',
                    cancelButtonText: 'Cancelar',
                    confirmButtonColor: '#16a34a', // Verde
                    denyButtonColor: '#dc2626'     // Rojo
                });

                if (result.isDismissed) return; // Si cancela, no agregamos nada al carrito
                
                if (result.isDenied) {
                    depositToCharge = parseFloat(product.deposit_price) * parseFloat(qty);
                }
            }

            const existingItem = this.cart.find(item => item.id === product.id && !item.is_service);
            const currentQty = existingItem ? parseFloat(existingItem.quantity) : 0;
            const newTotalQty = currentQty + parseFloat(qty);

            if (!product.is_service && newTotalQty > product.stock) {
                Swal.fire({icon: 'warning', title: 'Stock Insuficiente', text: `Límite: ${product.stock}`, confirmButtonColor: '#3e1717'});
                return;
            }

            if (existingItem) {
                existingItem.quantity = newTotalQty;
                existingItem.deposit_charged = (existingItem.deposit_charged || 0) + depositToCharge; 
            } else {
                this.cart.push({
                    ...product,
                    quantity: parseFloat(qty),
                    max_stock: product.stock,
                    deposit_charged: depositToCharge 
                });
            }
            
            this.clearSearch();
            const Toast = Swal.mixin({toast: true, position: 'top-end', showConfirmButton: false, timer: 1000});
            Toast.fire({icon: 'success', title: 'Agregado'});
        },

        async updateQuantity(item, delta) {
            // Si el cajero quiere AUMENTAR la cantidad y es retornable, preguntamos:
            if (item.is_returnable && delta > 0) {
                 const result = await Swal.fire({
                    title: '♻️ Producto Retornable',
                    text: '¿El cliente trajo envase para esta unidad extra?',
                    icon: 'question',
                    showDenyButton: true,
                    showCancelButton: true,
                    confirmButtonText: 'Sí',
                    denyButtonText: 'No (Cobrar)',
                    cancelButtonText: 'Cancelar',
                    confirmButtonColor: '#16a34a',
                    denyButtonColor: '#dc2626'
                });

                if (result.isDismissed) return;
                if (result.isDenied) {
                    item.deposit_charged = (item.deposit_charged || 0) + parseFloat(item.deposit_price);
                }
            }

            // Si el cajero quiere DISMINUIR la cantidad, debemos verificar si hay importes cobrados para quitar uno.
            if (item.is_returnable && delta < 0) {
                // Si el item tiene dinero de importe acumulado...
                if (item.deposit_charged > 0) {
                    // Le restamos el valor de 1 importe (porque estamos quitando 1 producto)
                    item.deposit_charged = Math.max(0, item.deposit_charged - parseFloat(item.deposit_price));
                }
            }

            const newQty = parseFloat(item.quantity) + delta;
            
            // Si la cantidad llega a 0, lo borramos del carrito
            if (newQty <= 0) {
                this.removeFromCart(this.cart.indexOf(item));
                return;
            }
            
            // Límite de stock
            if (!item.is_service && newQty > item.max_stock) {
                Swal.fire('Tope', 'Stock máximo alcanzado', 'info');
                return;
            }
            
            // Finalmente, actualizamos la cantidad visual
            item.quantity = newQty;
        },

        validateQuantity(item) {
            if (item.quantity < 0.001) item.quantity = 1;
            if (!item.is_service && item.quantity > item.max_stock) item.quantity = item.max_stock;
        },

        // --- ACTUALIZADO PARA SUMAR EL IMPORTE AL TOTAL ---
        get cartTotal() { 
            return this.cart.reduce((sum, item) => sum + this.calculateItemTotal(item) + (item.deposit_charged || 0), 0); 
        },

        get cardBaseAmount() {
            if (!this.payWithCard) return 0;
            const cashDebt = parseFloat(this.cashDebtInput) || 0;
            return Math.max(0, this.cartTotal - cashDebt);
        },
        get cardChargeAmount() {
            if (this.cardBaseAmount <= 0.01) return 0;
            return this.cardBaseAmount / 0.9594;
        },
        get commissionAmount() { return this.cardChargeAmount - this.cardBaseAmount; },
        get finalTotalToPay() { return this.cartTotal + this.commissionAmount; },
        get change() {
            if (this.cashReceivedInput === '') return 0;
            const received = parseFloat(this.cashReceivedInput) || 0;
            if (!this.payWithCard) { return Math.max(0, received - this.cartTotal); } 
            else {
                const debtCovered = parseFloat(this.cashDebtInput) || 0;
                if (debtCovered === 0) return 0; 
                return Math.max(0, received - debtCovered);
            }
        },
        calculateItemTotal(item) {
            let quantity = parseFloat(item.quantity);
            let total = 0;

            if (item.promotions && item.promotions.length > 0) {
                let sortedPromos = [...item.promotions].sort((a, b) => b.trigger - a.trigger);
                for (let promo of sortedPromos) {
                    let trigger = parseFloat(promo.trigger);
                    let price = parseFloat(promo.price);
                    if (quantity >= trigger) {
                        let numPacks = Math.floor(quantity / trigger);
                        total += numPacks * price;
                        quantity = quantity % trigger;
                    }
                }
            } else if (item.promo && quantity >= item.promo.trigger) {
                let numPacks = Math.floor(quantity / item.promo.trigger);
                total += numPacks * item.promo.price;
                quantity = quantity % item.promo.trigger;
            }

            total += quantity * parseFloat(item.price);
            return total;
        },

        hasActivePromo(item) {
            if (item.promotions && item.promotions.length > 0) {
                let minTrigger = Math.min(...item.promotions.map(p => p.trigger));
                return item.quantity >= minTrigger;
            }
            return item.promo && item.quantity >= item.promo.trigger; 
        },

        getAppliedPromos(item) {
            let quantity = parseFloat(item.quantity);
            let applied = [];
            if (item.promotions && item.promotions.length > 0) {
                let sortedPromos = [...item.promotions].sort((a, b) => b.trigger - a.trigger);
                for (let promo of sortedPromos) {
                    let trigger = parseFloat(promo.trigger);
                    if (quantity >= trigger) {
                        let numPacks = Math.floor(quantity / trigger);
                        let texto = `${numPacks} x ${promo.desc || 'Pack'} (${parseInt(trigger)}pz) - ${this.formatMoney(parseFloat(promo.price) * numPacks)}`;
                        applied.push(texto);
                        quantity = quantity % trigger;
                    }
                }
            } else if (item.promo && quantity >= item.promo.trigger) {
                let numPacks = Math.floor(quantity / item.promo.trigger);
                applied.push(`${numPacks} x Oferta (${item.promo.trigger}pz) - ${this.formatMoney(item.promo.price * numPacks)}`);
            }
            return applied;
        },

        removeFromCart(index) { this.cart.splice(index, 1); },
        formatMoney(value) { return new Intl.NumberFormat('es-MX', { style: 'currency', currency: 'MXN' }).format(value); },

        // --- NUEVA FUNCIÓN: DEVOLVER ENVASE RÁPIDO ---
        async devolverEnvase() {
            const { value: amount } = await Swal.fire({
                title: '♻️ Devolución de Envase',
                text: '¿Cuánto dinero vas a sacar de la caja para devolver al cliente?',
                input: 'number',
                inputAttributes: { min: 1, step: 0.50 },
                showCancelButton: true,
                confirmButtonText: 'Registrar Devolución',
                confirmButtonColor: '#ea580c', // Naranja
                inputValidator: (value) => { if (!value || value <= 0) return 'Ingresa un monto válido' }
            });

            if (amount) {
                const form = new FormData();
                form.append('amount', amount);
                
                try {
                    const res = await fetch('/api/pos/devolver-envase/', { method: 'POST', body: form });
                    const data = await res.json();
                    
                    if (data.status === 'success') {
                        Swal.fire({icon: 'success', title: '¡Abre la caja!', text: `Entrega $${amount} al cliente.`, confirmButtonColor: '#3e1717'});
                    } else {
                        Swal.fire('Error', data.message, 'error');
                    }
                } catch (e) { Swal.fire('Error', 'Fallo de conexión', 'error'); }
            }
        },

        async processTransaction(type) {
            if (this.cart.length === 0) return;
            
            let withdrawalBeneficiary = null;
            
            let receivedCash = parseFloat(this.cashReceivedInput) || 0;
            let changeGiven = this.change > 0 ? this.change : 0;

            if (type === 'SALE') {
                if (!this.payWithCard) {
                    if (receivedCash < this.cartTotal) { Swal.fire({icon: 'warning', title: 'Falta Dinero', confirmButtonColor: '#3e1717'}); return; }
                } else {
                    const debtCovered = parseFloat(this.cashDebtInput) || 0;
                    if (receivedCash < debtCovered) { Swal.fire({icon: 'warning', title: 'Falta Dinero', confirmButtonColor: '#3e1717'}); return; }
                }
            }
            
            if (type === 'WITHDRAWAL') {
                const { value: reason } = await Swal.fire({
                    title: 'Toma Interna',
                    input: 'text',
                    inputLabel: 'Responsable',
                    showCancelButton: true,
                    confirmButtonColor: '#3e1717',
                    inputValidator: (value) => !value && 'Requerido'
                });
                if (!reason) return;
                withdrawalBeneficiary = reason;
            }

            let method = 'CASH';
            let amountCash = 0;
            if (type === 'SALE') {
                if (this.payWithCard) {
                    amountCash = parseFloat(this.cashDebtInput) || 0;
                    method = (amountCash > 0) ? 'MIXED' : 'CARD';
                } else { amountCash = this.cartTotal; }
            }

            const payload = {
                action: type, 
                items: this.cart, 
                total_products: this.cartTotal, 
                payment_method: method, 
                amount_cash: amountCash,
                amount_card: this.payWithCard ? this.cardChargeAmount : 0, 
                card_commission: this.commissionAmount, 
                beneficiary: withdrawalBeneficiary,
                cash_received: receivedCash,
                change_given: changeGiven
            };

            try {
                const response = await fetch('/api/sale/process/', { method: 'POST', body: JSON.stringify(payload) });
                const result = await response.json();
                
                if (result.status === 'success') {
                    if (type === 'SALE') {
                        let msg = "";
                        if (changeGiven > 0) msg += `Cambio: <b class="text-green-600 text-3xl">${this.formatMoney(changeGiven)}</b>`;
                        Swal.fire({title: '¡Venta OK!', html: msg, icon: 'success', confirmButtonColor: '#3e1717', timer: 3000});
                        
                        // --- DISPARAR LA IMPRESIÓN ---
                        window.open(`/ticket/${result.sale_id}/`, '_blank', 'width=400,height=600');
                    } else {
                        Swal.fire('Registrado', 'Salida OK', 'success');
                    }
                    this.cart = []; this.cashReceivedInput = ''; this.cashDebtInput = ''; this.payWithCard = false;
                    this.fetchTopProducts();
                    this.mobileTab = 'products';
                } else {
                    Swal.fire({ icon: 'error', title: 'Error', text: result.error });
                }
            } catch (error) { Swal.fire({ icon: 'error', title: 'Error', text: 'Error de red' }); }
        }
    }
}