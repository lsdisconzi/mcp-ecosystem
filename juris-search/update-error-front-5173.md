error in console: react-dom_client.js?v=30b14ad4:14336 Download the React DevTools for a better development experience: https://react.dev/link/react-devtools
react-dom_client.js?v=30b14ad4:3540 Uncaught Error: Objects are not valid as a React child (found: object with keys {nome, cargo}). If you meant to render a collection of children, use an array instead.
    at throwOnInvalidObjectTypeImpl (react-dom_client.js?v=30b14ad4:3540:10)
    at throwOnInvalidObjectType (react-dom_client.js?v=30b14ad4:3544:105)
    at reconcileChildFibersImpl (react-dom_client.js?v=30b14ad4:3857:6)
    at react-dom_client.js?v=30b14ad4:3869:28
    at reconcileChildren (react-dom_client.js?v=30b14ad4:5386:46)
    at beginWork (react-dom_client.js?v=30b14ad4:6200:1569)
    at runWithFiberInDEV (react-dom_client.js?v=30b14ad4:851:66)
    at performUnitOfWork (react-dom_client.js?v=30b14ad4:8429:92)
    at workLoopSync (react-dom_client.js?v=30b14ad4:8325:37)
    at renderRootSync (react-dom_client.js?v=30b14ad4:8309:6)
react-dom_client.js?v=30b14ad4:5258 An error occurred in the <span> component.

Consider adding an error boundary to your tree to customize error handling behavior.
Visit https://react.dev/link/error-boundaries to learn more about error boundaries.

defaultOnUncaughtError @ react-dom_client.js?v=30b14ad4:5258
>>>>>>>>>>>>>>The error you're seeing happens because you're trying to render a raw JavaScript object directly inside JSX. React can only render primitives (strings, numbers) or other React elements – not plain objects.

Looking at the message:
> found: object with keys `{nome, cargo}`

That means somewhere in a `<span>` (or another component), you wrote something like:

```jsx
<span>{objeto}</span>   // or: {algumObjeto}
```

Instead of accessing a specific property like:

```jsx
<span>{objeto.nome}</span>
// or
<span>{objeto.cargo}</span>
```

### How to fix it

1. **Render a specific string property from the object**  
   If you want to show the person’s name:
   ```jsx
   <span>{obj.nome}</span>
   ```
   Or both name and role:
   ```jsx
   <span>{obj.nome} - {obj.cargo}</span>
   ```

2. **If you meant to render a list of objects** (like an array of employees), you need to `.map()` over the array and return JSX for each item:
   ```jsx
   const lista = [
     { nome: 'Ana', cargo: 'Dev' },
     { nome: 'João', cargo: 'Designer' },
   ];

   return (
     <ul>
       {lista.map((pessoa, index) => (
         <li key={index}>
           {pessoa.nome} – {pessoa.cargo}
         </li>
       ))}
     </ul>
   );
   ```

3. **Check any parent that passes the whole object as children**  
   For example, you might have accidentally done:
   ```jsx
   <MeuSpan>{objetoComNomeECargo}</MeuSpan>
   ```
   Instead of passing a string.

The error boundary mention is just React suggesting you wrap parts of the tree to catch errors gracefully, but the root cause is always trying to render an object as a React child.

Look for the `<span>` mentioned in the stack trace and change it to render a primitive value from your object. That will solve the issue.